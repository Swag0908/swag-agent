package com.swag.chat.stream;

import org.springframework.ai.chat.client.ChatClientResponse;
import org.springframework.ai.chat.messages.AssistantMessage;
import org.springframework.ai.chat.model.ChatResponse;
import org.springframework.ai.chat.model.Generation;
import org.springframework.http.codec.ServerSentEvent;
import org.springframework.stereotype.Component;
import reactor.core.publisher.Flux;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.function.Supplier;

/**
 * 把 Spring AI 的流式响应翻译成前端可读的 SSE 事件流。
 *
 * <p><b>两类事件，来源不同（本项目踩过的最大一个坑）</b>：
 *
 * <ul>
 *   <li><b>正文 / 思考过程</b>：来自 {@code ChatResponse} 流，逐字增量。</li>
 *   <li><b>工具状态</b>：来自 {@link ToolEventRelay}——真实链路里模型的工具调用请求
 *       <em>不会出现在响应流里</em>（Spring AI 在 API 层就合并并执行了工具，
 *       实测一次带工具的回答共 90 条响应、含工具调用的 0 条），
 *       只能靠工具执行时发出的观测事件。所以这里把两条来源「合流」成一条时间线。</li>
 * </ul>
 *
 * <p>正文与思考过程的区分规则：模型调用工具前可能先说一句「我先查一下」，之后才给最终回答。
 * 由于工具事件必然先于工具之后的文字到达，就以「本轮流是否已经出现过工具事件」划线——
 * 没出现过 → 文字算最终回答；出现过 → 文字算过渡说明（只展示、不落库）。
 */
@Component
public class ChatStreamBridge {

    private final ToolEventRelay relay;

    public ChatStreamBridge(ToolEventRelay relay) {
        this.relay = relay;
    }

    /**
     * 包装一条聊天响应流。
     *
     * @param responses 模型流式响应（只含正文；工具调用不在其中）
     * @param session   已登记的工具状态信箱，可为 null（没有审计上下文时）
     * @param readyData {@code ready} 事件负载，例如 {"conversation_id": 12}
     * @return SSE 事件流，同时携带「本轮最终回答」供落库
     */
    public SseStream bridge(Flux<ChatClientResponse> responses,
                            ToolEventRelay.Session session,
                            Map<String, Object> readyData) {
        State state = new State();

        // 内容流水线：模型响应 → 正文 / 思考过程 / 收尾事件。
        // cache() 必不可少：它既要转发给前端、又要当「跑完」的终止信号（等于订阅两次）。
        // 没有 cache 时模型响应会被消费两遍，正文和「最终回答」都会翻倍（测试抓到过）。
        Flux<ServerSentEvent<String>> content = responses
                .concatMap(response -> Flux.fromIterable(onResponse(response, session, state)))
                .concatWith(Flux.defer(() -> Flux.fromIterable(onComplete(state, session))))
                .cache();

        // 工具状态是「旁路」，不参与完成判定：模型响应跑完，本轮就结束。
        // 用 takeUntilOther(contentCompletion) 收尾，而不是「谁先完成谁算完」——
        // 否则工具状态信箱一直开着，两边互等会挂住整条流（踩过）。
        //
        // ⚠️ 这里刻意不提前 subscribe() 一次内容流水线去取完成信号：
        // 那种「探针订阅」会绕过 AuditContextHolder.propagate(...) 注入的审计上下文，
        // 导致 advisor 抛「No audit context is active」（线上真实故障就在这里）。
        Flux<ServerSentEvent<String>> toolChannel = session == null
                ? Flux.empty()
                : session.asFlux().takeUntilOther(content.ignoreElements());

        return new SseStream(Flux.just(SseEvents.of(SseEvents.EVENT_READY, readyData))
                .concatWith(Flux.merge(content, toolChannel))
                .concatWith(Flux.just(SseEvents.of(SseEvents.EVENT_DONE, Map.of())))
                .onErrorResume(e -> {
                    Map<String, Object> payload = new LinkedHashMap<>();
                    payload.put("message", e.getMessage() == null ? "服务异常" : e.getMessage());
                    return Flux.just(SseEvents.of(SseEvents.EVENT_ERROR, payload));
                }),
                state::content);
    }

    /** 单条模型响应 → 若干 SSE 事件。 */
    private List<ServerSentEvent<String>> onResponse(ChatClientResponse clientResponse,
                                                     ToolEventRelay.Session session,
                                                     State state) {
        List<ServerSentEvent<String>> events = new ArrayList<>();
        ChatResponse response = clientResponse == null ? null : clientResponse.chatResponse();
        if (response == null) {
            return events;
        }
        Generation result = response.getResult();
        AssistantMessage message = result == null ? null : result.getOutput();
        if (message == null || message.getText() == null || message.getText().isEmpty()) {
            return events;
        }

        String text = message.getText();
        if (session != null && session.hasToolEvents()) {
            // 工具之后的文字是「过渡说明」：实时展示但不落库；
            // 如果模型就此收尾，onComplete 会把它补一条 content 事件转正。
            state.reasoningText.append(text);
            events.add(SseEvents.sse(SseEvents.EVENT_REASONING,
                    ChatStreamEvent.of(SseEvents.EVENT_REASONING, "text", text)));
        }
        else {
            state.answer.append(text);
            events.add(SseEvents.sse(SseEvents.EVENT_CONTENT,
                    ChatStreamEvent.of(SseEvents.EVENT_CONTENT, "text", text)));
        }
        return events;
    }

    /**
     * 流结束前的收尾：**工具之后的最后一段文字就是最终回答**。
     *
     * <p>模型说过工具、又给了结论时，「结论」是在工具之后才出现的（所以它一路被标成
     * 「过渡说明」）。此时必须把它转正为 {@code content} 并落库，同时把工具之前那句铺垫
     * 从「最终回答」的位置上撤下来——它只是过程。
     *
     * <p>这里同时下发 {@code segment_boundary}，让前端把已经显示在正文区的铺垫文字搬进
     * 「思考过程」，保证屏幕上留下的正文和落库内容一致。
     */
    private List<ServerSentEvent<String>> onComplete(State state, ToolEventRelay.Session session) {
        List<ServerSentEvent<String>> events = new ArrayList<>();
        boolean toolsRan = session != null && session.hasToolEvents();
        if (!toolsRan) {
            return events;
        }
        // 干过活：工具之前发出去的文字都是铺垫，不该留在正文里
        String finalAnswer = state.reasoningText.toString();
        boolean preToolTextWasAnswer = state.answer.length() > 0;
        state.answer.setLength(0);
        state.reasoningText.setLength(0);
        if (finalAnswer.isEmpty()) {
            // 模型只调工具、没再说话：正文就是空的，前端把铺垫搬进思考过程即可
            if (preToolTextWasAnswer) {
                events.add(SseEvents.of(SseEvents.EVENT_SEGMENT_BOUNDARY,
                        Map.of("reason", "tool_only")));
            }
            return events;
        }
        state.answer.append(finalAnswer);
        if (preToolTextWasAnswer) {
            // 之前那段是「我先查一下」式的铺垫，前端要把它从正文区搬走
            events.add(SseEvents.of(SseEvents.EVENT_SEGMENT_BOUNDARY, Map.of("reason", "final_answer")));
        }
        events.add(SseEvents.sse(SseEvents.EVENT_CONTENT,
                ChatStreamEvent.of(SseEvents.EVENT_CONTENT, "text", finalAnswer)));
        return events;
    }

    /** 一轮聊天的全部临时状态。 */
    private static final class State {
        private final StringBuilder answer = new StringBuilder();
        private final StringBuilder reasoningText = new StringBuilder();

        String content() {
            return answer.toString();
        }
    }

    /** 桥接结果：给前端的事件流 + 本轮要落库的最终回答。 */
    public record SseStream(Flux<ServerSentEvent<String>> events, Supplier<String> content) {
    }
}

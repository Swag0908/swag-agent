package com.swag.chat.stream;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.ai.chat.client.ChatClientResponse;
import org.springframework.ai.chat.messages.AssistantMessage;
import org.springframework.ai.chat.model.ChatResponse;
import org.springframework.ai.chat.model.Generation;
import org.springframework.http.codec.ServerSentEvent;
import reactor.core.publisher.Flux;
import tools.jackson.databind.json.JsonMapper;

import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicLong;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertNotNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 流式事件桥的行为测试：模型响应 → 正文 / 思考过程 / ready / done。
 *
 * <p>工具状态事件不在这里产生（它来自工具执行观测，见 {@link ToolEventRelayTests}）。
 * 测试里的模型响应刻意不带工具调用信息——真实链路正是如此。
 */
class ChatStreamBridgeTests {

    private ChatStreamBridge bridge;

    @BeforeEach
    void setUp() {
        bridge = new ChatStreamBridge(null);
    }

    @Test
    void emitsContentForAnswerWithNoToolCall() {
        Flux<ChatClientResponse> responses = Flux.just(
                response("你好，"),
                response("我是助手。"));

        ChatStreamBridge.SseStream stream = bridge.bridge(responses, null, Map.of());
        List<ServerSentEvent<String>> events = stream.events().collectList().block();

        assertNotNull(events);
        assertEquals("ready", events.get(0).event());
        assertEquals("done", events.get(events.size() - 1).event());
        assertEquals("你好，我是助手。", stream.content().get());

        List<ServerSentEvent<String>> contents = eventsOf(events, SseEvents.EVENT_CONTENT);
        assertEquals(2, contents.size());
        assertEquals("你好，", textOf(contents.get(0)));
        assertEquals("我是助手。", textOf(contents.get(1)));
    }


    @Test
    void answerAfterToolBecomesContentAndPreToolTextIsDemoted() {
        // 真实时序：模型先说一句铺垫 → 工具执行（旁路投递）→ 模型给出最终回答。
        // 用 delayElements 把响应摊开，好在第一段到达之后插入「工具已执行」这一事实。
        ToolEventRelay relay = new ToolEventRelay(new ToolActivityDescriber(
                toolName -> null, JsonMapper.builder().build()));
        ToolEventRelay.Session session = relay.open("audit-test");
        ChatStreamBridge relayBridge = new ChatStreamBridge(relay);

        Flux<ChatClientResponse> responses = Flux.just(
                        response("我先查一下。"),
                        response("现在是下午三点。"))
                .delayElements(java.time.Duration.ofMillis(150));

        ChatStreamBridge.SseStream stream = relayBridge.bridge(responses, session, Map.of());
        List<ServerSentEvent<String>> events = stream.events()
                .doOnNext(event -> {
                    // 第一段文字（铺垫）到达后再标记「工具跑过了」，模拟真实顺序
                    if (SseEvents.EVENT_CONTENT.equals(event.event())) {
                        session.markToolEventsForTest();
                    }
                })
                .collectList()
                .block(java.time.Duration.ofSeconds(10));
        relay.close(session);

        assertNotNull(events);
        // 落库的回答必须是工具之后那句，而不是铺垫
        assertEquals("现在是下午三点。", stream.content().get());
        // 前端会收到边界事件，把铺垫从正文区搬进思考过程
        assertEquals(1, eventsOf(events, SseEvents.EVENT_SEGMENT_BOUNDARY).size());
        List<ServerSentEvent<String>> contents = eventsOf(events, SseEvents.EVENT_CONTENT);
        assertEquals("现在是下午三点。", textOf(contents.get(contents.size() - 1)));
    }

    @Test
    void fluxCompletesInsteadOfHanging() {
        List<ServerSentEvent<String>> events = bridge
                .bridge(Flux.just(response("ok")), null, Map.of())
                .events()
                .collectList()
                .block(java.time.Duration.ofSeconds(5));

        assertNotNull(events, "流应在超时前正常结束");
        assertEquals(3, events.size()); // ready + content + done
    }

    @Test
    void eventsArriveOneByOneInsteadOfBeingBuffered() {
        // 「流式」的底线：事件必须边产生边下发，不能等模型全部说完再一次性吐出。
        Flux<ChatClientResponse> responses = Flux.just(
                        response("第一段。"),
                        response("第二段。"),
                        response("第三段。"))
                .delayElements(java.time.Duration.ofMillis(150));

        long began = System.nanoTime();
        AtomicLong firstEventAt = new AtomicLong(-1);
        AtomicLong completedAt = new AtomicLong(-1);

        bridge.bridge(responses, null, Map.of())
                .events()
                .doOnNext(event -> firstEventAt.compareAndSet(-1, System.nanoTime() - began))
                .doOnComplete(() -> completedAt.set(System.nanoTime() - began))
                .blockLast(java.time.Duration.ofSeconds(10));

        long totalMs = completedAt.get() / 1_000_000;
        long firstMs = firstEventAt.get() / 1_000_000;
        assertTrue(firstMs >= 0, "应至少收到一条事件");
        assertTrue(firstMs < totalMs / 2,
                "首条事件到达时间 " + firstMs + "ms 应远小于整条流耗时 " + totalMs + "ms（否则说明被缓冲了）");
    }

    // ---------- 测试辅助 ----------

    private static ChatClientResponse response(String content) {
        AssistantMessage message = AssistantMessage.builder().content(content).build();
        return ChatClientResponse.builder()
                .chatResponse(new ChatResponse(List.of(new Generation(message))))
                .build();
    }

    private static List<ServerSentEvent<String>> eventsOf(List<ServerSentEvent<String>> events,
                                                          String eventName) {
        return events.stream().filter(event -> eventName.equals(event.event())).toList();
    }

    /** 取出 content / reasoning 事件里的 text 字段。 */
    private static String textOf(ServerSentEvent<String> event) {
        return JsonMapper.builder().build().readTree(event.data())
                .get("data").get("text").asString();
    }
}

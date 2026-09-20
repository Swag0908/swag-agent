package com.swag.chat.stream;

import com.swag.audit.context.AuditContextHolder;
import com.swag.audit.context.AuditRequestContext;
import org.junit.jupiter.api.Test;
import org.springframework.ai.tool.definition.ToolDefinition;
import org.springframework.ai.tool.observation.ToolCallingObservationContext;
import org.springframework.http.codec.ServerSentEvent;
import reactor.core.publisher.Flux;
import tools.jackson.databind.json.JsonMapper;

import java.time.Duration;
import java.util.List;
import java.util.UUID;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 工具状态中继的行为测试。
 *
 * <p>这是线上「工具有执行、前端却收不到状态」的那个环节：模型响应里看不到工具调用，
 * 只能靠工具执行观测按 auditId 投递到对应的聊天流。这里就把这条路径钉死。
 */
class ToolEventRelayTests {

    private final ToolEventRelay relay = new ToolEventRelay(new ToolActivityDescriber(
            toolName -> null, JsonMapper.builder().build()));

    /** 模拟 AuditContextFilter 建立的请求审计上下文。 */
    private static AuditRequestContext auditContext(UUID auditId) {
        return new AuditRequestContext(auditId, "req-1", "t1", "7", null, null, "8");
    }

    private static org.springframework.ai.chat.client.ChatClientResponse textResponse(String text) {
        return org.springframework.ai.chat.client.ChatClientResponse.builder()
                .chatResponse(new org.springframework.ai.chat.model.ChatResponse(List.of(
                        new org.springframework.ai.chat.model.Generation(
                                org.springframework.ai.chat.messages.AssistantMessage.builder()
                                        .content(text).build()))))
                .build();
    }

    private static ToolCallingObservationContext toolContext(String callId, String name, String arguments) {
        return ToolCallingObservationContext.builder()
                .toolDefinition(ToolDefinition.builder()
                        .name(name)
                        .description("测试用工具")
                        .inputSchema("{}")
                        .build())
                .toolCallId(callId)
                .toolType("FUNCTION")
                .toolCallArguments(arguments)
                .build();
    }

    @Test
    void toolEventsAreDeliveredToTheMatchingChatStream() {
        UUID auditId = UUID.randomUUID();
        ToolEventRelay.Session session = relay.open(auditId.toString());

        // 工具在自己的线程上执行，观测回调也带同样的审计上下文
        try (AuditContextHolder.Scope ignored = AuditContextHolder.open(auditContext(auditId))) {
            relay.onToolStart(toolContext("call-1", "webSearch", "{\"query\":\"DeepSeek\"}"));
            relay.onToolStop(toolContext("call-1", "webSearch", "{\"query\":\"DeepSeek\"}"), true);
        }

        // 信箱是 unicast + 缓冲的：先把事件投进去，再消费也能全部拿到。
        // 注意信箱要等流结束才关闭，所以用 take(2) 取够就收，不能 collectList（会一直等完成）。
        List<ServerSentEvent<String>> received = session.asFlux()
                .take(2)
                .collectList()
                .block(Duration.ofSeconds(5));
        relay.close(session);

        assertTrue(session.hasToolEvents(), "有工具跑过就应该标记出来（正文/过程靠它分界）");
        assertEquals(2, received.size());
        assertEquals("tool_call", received.get(0).event());
        assertTrue(received.get(0).data().contains("\"status\":\"RUNNING\""), received.get(0).data());
        assertTrue(received.get(0).data().contains("webSearch"), received.get(0).data());
        assertTrue(received.get(0).data().contains("联网搜索"), received.get(0).data());
        assertTrue(received.get(0).data().contains("DeepSeek"), received.get(0).data());
        assertTrue(received.get(1).data().contains("\"status\":\"SUCCEEDED\""), received.get(1).data());
    }

    @Test
    void noSessionMeansNothingIsEmittedAndNothingBreaks() {
        // 没有登记信箱时（例如非聊天请求触发了工具），不能抛异常，也不能投错地方
        try (AuditContextHolder.Scope ignored = AuditContextHolder.open(auditContext(UUID.randomUUID()))) {
            relay.onToolStart(toolContext("call-x", "getCurrentTime", "{}"));
            relay.onToolStop(toolContext("call-x", "getCurrentTime", "{}"), false);
        }
    }

    @Test
    void eventsOnlyGoToTheSessionWithTheSameAuditId() {
        UUID mine = UUID.randomUUID();
        UUID other = UUID.randomUUID();
        ToolEventRelay.Session mySession = relay.open(mine.toString());
        ToolEventRelay.Session otherSession = relay.open(other.toString());

        try (AuditContextHolder.Scope ignored = AuditContextHolder.open(auditContext(mine))) {
            relay.onToolStart(toolContext("call-mine", "listTodayTodos", "{}"));
        }

        List<ServerSentEvent<String>> mineEvents = mySession.asFlux()
                .take(1)
                .collectList()
                .block(Duration.ofSeconds(5));
        relay.close(mySession);
        relay.close(otherSession);

        assertTrue(mineEvents != null && mineEvents.size() == 1, "自己的事件应投到自己这条流");
        assertTrue(mineEvents.get(0).data().contains("listTodayTodos"), mineEvents.get(0).data());
        // 投递是按 auditId 精确查表；另一条流的标记必须保持为「没干过活」
        assertTrue(mySession.hasToolEvents());
        assertFalse(otherSession.hasToolEvents(), "别的流不应被标记成干过活");
    }

    @Test
    void relayedEventsMergeIntoTheChatEventStream() {
        // 把中继和桥接器接起来：工具事件应插进 ready 与 done 之间
        UUID auditId = UUID.randomUUID();
        ToolEventRelay.Session session = relay.open(auditId.toString());
        ChatStreamBridge bridge = new ChatStreamBridge(relay);

        // 让模型响应延迟 200ms，好在它跑完之前把工具事件投进去（模拟真实时序）
        Flux<org.springframework.ai.chat.client.ChatClientResponse> slowResponses =
                Flux.just(textResponse("查到了。"))
                        .delayElements(Duration.ofMillis(200));

        List<ServerSentEvent<String>> collected = bridge
                .bridge(slowResponses, session, java.util.Map.of("conversation_id", 8))
                .events()
                .doOnSubscribe(subscription -> new Thread(() -> {
                    try {
                        Thread.sleep(80);
                        try (AuditContextHolder.Scope ignored =
                                     AuditContextHolder.open(auditContext(auditId))) {
                            relay.onToolStart(toolContext("call-2", "getCurrentTime", "{}"));
                            relay.onToolStop(toolContext("call-2", "getCurrentTime", "{}"), true);
                        }
                    }
                    catch (InterruptedException ignored) {
                        Thread.currentThread().interrupt();
                    }
                }).start())
                .collectList()
                .block(Duration.ofSeconds(10));
        relay.close(session);

        assertTrue(collected != null);
        assertEquals("ready", collected.get(0).event());
        assertEquals("done", collected.get(collected.size() - 1).event());
        // 关键：工具状态事件插进了 ready 与 done 之间
        List<ServerSentEvent<String>> tools = collected.stream()
                .filter(event -> SseEvents.EVENT_TOOL.equals(event.event()))
                .toList();
        assertEquals(2, tools.size(), "工具的开始与完成都应出现在事件流里：" + collected);
        assertTrue(tools.get(0).data().contains("\"status\":\"RUNNING\""), tools.get(0).data());
    }
}

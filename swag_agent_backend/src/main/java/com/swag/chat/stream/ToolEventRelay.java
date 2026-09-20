package com.swag.chat.stream;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.ai.tool.observation.ToolCallingObservationContext;
import org.springframework.stereotype.Component;
import reactor.core.publisher.Sinks;

import java.util.Map;
import java.util.Set;
import java.util.concurrent.ConcurrentHashMap;

/**
 * 工具状态中继：把「工具开始执行 / 执行结束」实时送进对应的那条聊天流。
 *
 * <p><b>为什么需要它（踩过的坑）</b>：真实链路里模型的工具调用请求
 * <em>不会出现在 {@code ChatResponse} 流里</em>——Spring AI 的 DeepSeek 实现在 API 层就把
 * 分片的工具调用合并掉、直接执行工具，只把最终正文交给上层（实测：一次带工具的回答共 90 条
 * 响应，含工具调用的为 0 条）。因此判断「正在用哪个工具」只能靠工具执行时自己发的观测事件，
 * 不能靠解析模型响应。
 *
 * <p><b>怎么找到「是哪条聊天流」</b>：用审计上下文里的 {@code auditId} 当钥匙。
 * 每次 HTTP 请求都会由 {@code AuditContextFilter} 生成唯一的 auditId 并放进 ThreadLocal，
 * 斗篷式地贯穿整条链路；聊天流开始时用它登记一个「信箱」，工具观测回调按同一个 auditId 投递。
 * 工具执行与观测回调在同一线程上同步发生，因此这里读到的上下文与工具本身读到的一致。
 */
@Component
public class ToolEventRelay {

    private static final Logger log = LoggerFactory.getLogger(ToolEventRelay.class);

    private static final String STATUS_RUNNING = "RUNNING";
    private static final String STATUS_SUCCEEDED = "SUCCEEDED";
    private static final String STATUS_FAILED = "FAILED";

    private final ToolActivityDescriber describer;

    /** auditId → 这条聊天流的信箱。 */
    private final Map<String, Session> sessions = new ConcurrentHashMap<>();

    /** toolCallId → 它属于哪条流（保证「完成」事件能回到正确的流）。 */
    private final Map<String, Session> byCallId = new ConcurrentHashMap<>();

    public ToolEventRelay(ToolActivityDescriber describer) {
        this.describer = describer;
    }

    // ------------------------------------------------------------------
    // 生命周期
    // ------------------------------------------------------------------

    /** 为一条聊天流登记信箱。 */
    public Session open(String auditId) {
        Session session = new Session(auditId);
        sessions.put(auditId, session);
        return session;
    }

    /** 流结束：注销信箱并清掉尚未收尾的配对。 */
    public void close(Session session) {
        if (session == null) {
            return;
        }
        if (session.auditId != null) {
            sessions.remove(session.auditId, session);
        }
        session.callIds.forEach(byCallId::remove);
        session.sink.tryEmitComplete();
    }

    // ------------------------------------------------------------------
    // 观测回调入口
    // ------------------------------------------------------------------

    /** 工具开始执行。 */
    public void onToolStart(ToolCallingObservationContext context) {
        Session session = currentSession();
        String callId = context.getToolCallId();
        String name = context.getToolDefinition().name();
        String arguments = context.getToolCallArguments();
        if (session != null) {
            session.toolEvents.set(true);
        }
        if (session != null && callId != null && !callId.isBlank()) {
            session.running.put(callId, new ToolCall(name, arguments, System.currentTimeMillis()));
            session.callIds.add(callId);
            byCallId.put(callId, session);
        }
        emit(session, name, arguments, callId, STATUS_RUNNING, null);
    }

    /** 工具执行成功（或失败）。 */
    public void onToolStop(ToolCallingObservationContext context, boolean succeeded) {
        Session session = byCallId.remove(context.getToolCallId());
        String name = context.getToolDefinition().name();
        String arguments = context.getToolCallArguments();
        Long duration = null;
        if (session != null) {
            ToolCall call = session.running.remove(context.getToolCallId());
            if (call != null) {
                duration = System.currentTimeMillis() - call.startedAt();
            }
        }
        emit(session, name, arguments, context.getToolCallId(),
                succeeded ? STATUS_SUCCEEDED : STATUS_FAILED, duration);
    }

    // ------------------------------------------------------------------
    // 内部
    // ------------------------------------------------------------------

    /** 当前线程正在服务的那条聊天流：由 auditId 关联。 */
    private Session currentSession() {
        return com.swag.audit.context.AuditContextHolder.current()
                .map(context -> sessions.get(context.auditId().toString()))
                .orElse(null);
    }

    private void emit(Session session, String toolName, String arguments,
                      String callId, String status, Long durationMs) {
        if (session == null) {
            log.debug("工具 {} 的状态无处投递（不是聊天流发起的调用）", toolName);
            return;
        }
        ToolActivityDescriber.Activity activity = describer.describe(toolName, arguments);
        Sinks.EmitResult result = session.sink.tryEmitNext(SseEvents.sse(
                SseEvents.EVENT_TOOL,
                ChatStreamEvent.toolCall(toolName, status, activity.display(),
                        activity.detail(), callId, durationMs)));
        if (result.isFailure()) {
            // 客户端断开后信箱可能已关闭；这只是状态展示，绝不能影响工具本身的返回
            log.debug("工具状态事件投递失败（{}）：{}", result, toolName);
        }
    }

    private record ToolCall(String name, String arguments, long startedAt) {
    }

    /** 一条聊天流的信箱。 */
    public static final class Session {
        private final String auditId;
        private final java.util.concurrent.atomic.AtomicBoolean toolEvents = new java.util.concurrent.atomic.AtomicBoolean();
        private final Sinks.Many<org.springframework.http.codec.ServerSentEvent<String>> sink =
                Sinks.many().unicast().onBackpressureBuffer();
        private final Set<String> callIds = ConcurrentHashMap.newKeySet();
        private final Map<String, ToolCall> running = new ConcurrentHashMap<>();

        private Session(String auditId) {
            this.auditId = auditId;
        }

        /** 供流式响应合并的工具状态事件流。 */
        public reactor.core.publisher.Flux<org.springframework.http.codec.ServerSentEvent<String>> asFlux() {
            return sink.asFlux();
        }

        /** 本轮流是否已经出现过工具事件（正文与思考过程的分界线）。 */
        public boolean hasToolEvents() {
            return toolEvents.get();
        }

        /** 仅供测试：直接标记「本轮流干过活」，省去构造观测上下文。 */
        void markToolEventsForTest() {
            toolEvents.set(true);
        }
    }
}

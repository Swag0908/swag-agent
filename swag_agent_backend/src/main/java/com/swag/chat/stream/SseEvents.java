package com.swag.chat.stream;

import org.springframework.http.codec.ServerSentEvent;

import java.util.Map;

/**
 * SSE 事件的构造。
 *
 * <p>前端按 {@code event:} 名分流，{@code data:} 是 {@link ChatStreamEvent} 的单行 JSON。
 * 事件类型见 {@link #EVENT_READY} 等常量。
 */
public final class SseEvents {

    /** 流已建立，data 里带 conversation_id，前端用来对齐会话列表。 */
    public static final String EVENT_READY = "ready";
    /** 最终回答的增量文本（这段会被落库）。 */
    public static final String EVENT_CONTENT = "content";
    /** 工具调用前后的过渡文字，只展示、不落库。 */
    public static final String EVENT_REASONING = "reasoning";
    /** 工具调用状态：RUNNING / SUCCEEDED。 */
    public static final String EVENT_TOOL = "tool_call";
    /** 出错提示（data.message 是原因）。 */
    public static final String EVENT_ERROR = "error";
    /** 本轮结束。 */
    public static final String EVENT_DONE = "done";
    /**
     * 阶段边界：模型开始调用工具，之前已经当作回答发出去的铺垫文字要降级成「思考过程」。
     * 前端收到后把正文搬到思考区并清空正文，保证落库的正文只有真正的最终回答。
     */
    public static final String EVENT_SEGMENT_BOUNDARY = "segment_boundary";

    private SseEvents() {
    }

    public static ServerSentEvent<String> sse(String eventName, ChatStreamEvent payload) {
        return ServerSentEvent.<String>builder()
                .event(eventName)
                .data(payload.toJson())
                .build();
    }

    /** 便捷方法：直接发一个「只有键值对」的事件。 */
    public static ServerSentEvent<String> of(String eventName, Map<String, Object> data) {
        return sse(eventName, new ChatStreamEvent(eventName, data));
    }
}

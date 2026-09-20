package com.swag.chat.stream;

import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.json.JsonMapper;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 聊天流式的统一事件负载（序列化成 JSON 放进 SSE 的 data 字段）。
 *
 * <p>事件类型：
 * <ul>
 *   <li>{@code ready}：流已建立，回传会话 id（前端首问时用来对齐列表）。</li>
 *   <li>{@code content}：回答正文的一个增量片段（要落库的那部分）。</li>
 *   <li>{@code reasoning}：工具调用前后模型的铺垫文字，只用于展示，不落库。</li>
 *   <li>{@code tool_call}：工具调用状态（RUNNING = 开始执行，SUCCEEDED / FAILED = 结束）。</li>
 *   <li>{@code error}：链路异常。</li>
 *   <li>{@code done}：本轮结束，前端据此收起所有「正在干活」的提示。</li>
 * </ul>
 */
public record ChatStreamEvent(String type, Map<String, Object> data) {

    /** SSE 的 data 只允许单行，序列化失败时降级为空对象，避免整条流因此中断。 */
    private static final ObjectMapper MAPPER = JsonMapper.builder().build();

    public static ChatStreamEvent of(String type) {
        return new ChatStreamEvent(type, Map.of());
    }

    public static ChatStreamEvent of(String type, String key, Object value) {
        Map<String, Object> payload = new LinkedHashMap<>();
        if (key != null) {
            payload.put(key, value);
        }
        return new ChatStreamEvent(type, payload);
    }

    /**
     * 工具状态事件。字段名用 snake_case，和现有接口风格保持一致，前端直接读。
     *
     * @param name       工具名（模型调用名，例如 webSearch）
     * @param status     RUNNING / SUCCEEDED / FAILED
     * @param display    人话描述，例如「正在联网搜索：DeepSeek 最新发布…」
     * @param detail     参数摘要
     * @param callId     模型给出的 tool call id，用来把开始与结束配对
     * @param durationMs 执行耗时（结束时才有）
     */
    public static ChatStreamEvent toolCall(String name, String status, String display,
                                           String detail, String callId, Long durationMs) {
        Map<String, Object> payload = new LinkedHashMap<>();
        payload.put("name", name);
        payload.put("status", status);
        payload.put("display", display);
        if (detail != null && !detail.isBlank()) {
            payload.put("detail", detail);
        }
        if (callId != null) {
            payload.put("call_id", callId);
        }
        if (durationMs != null) {
            payload.put("duration_ms", durationMs);
        }
        return new ChatStreamEvent("tool_call", payload);
    }

    public String toJson() {
        try {
            return MAPPER.writeValueAsString(this);
        }
        catch (RuntimeException e) {
            return "{\"type\":\"" + type + "\"}";
        }
    }
}

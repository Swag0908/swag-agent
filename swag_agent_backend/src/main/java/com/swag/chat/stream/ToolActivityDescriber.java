package com.swag.chat.stream;

import tools.jackson.databind.JsonNode;
import tools.jackson.databind.ObjectMapper;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.ai.tool.ToolCallback;
import org.springframework.ai.tool.resolution.ToolCallbackResolver;
import org.springframework.stereotype.Component;

import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 工具状态的翻译官：把「工具名 + 入参」变成前端可以直接显示的人话。
 *
 * <p>它只负责「怎么写」，不负责「什么时候写」——事件时机由 {@link ChatStreamBridge}
 * 按模型响应的先后顺序决定（模型一提出工具调用就算开始，等到下一轮响应就说明工具跑完了）。
 * 这样工具事件天然落在正确的顺序位置，不需要额外的线程协调。
 */
@Component
public class ToolActivityDescriber {

    private static final Logger log = LoggerFactory.getLogger(ToolActivityDescriber.class);

    /** 动作词表：把工具名翻译成「正在干嘛」。未收录的工具按兜底规则取名。 */
    private static final Map<String, String> ACTION_WORDS = actionWords();

    /** 参数摘要优先读取的字段（按先后顺序），都取不到时退化成一整段截断文本。 */
    private static final String[] DETAIL_KEYS = {
            "query", "keyword", "name", "title", "url", "content", "text", "ref", "date", "id"
    };

    private static final int DETAIL_MAX_CHARS = 48;

    private final ToolCallbackResolver toolCallbackResolver;
    private final ObjectMapper objectMapper;

    public ToolActivityDescriber(ToolCallbackResolver toolCallbackResolver, ObjectMapper objectMapper) {
        this.toolCallbackResolver = toolCallbackResolver;
        this.objectMapper = objectMapper;
    }

    /**
     * 生成展示用的人话描述。动作词优先取人工词表；没收录的工具用
     * {@code @Tool(description = ...)} 的第一句兜底，保证以后新加的工具也有可读提示。
     */
    public Activity describe(String toolName, String arguments) {
        String action = ACTION_WORDS.get(toolName);
        if (action == null) {
            action = fallbackAction(toolName);
        }
        String detail = detail(arguments);
        String display = detail == null ? "正在" + action + "…" : "正在" + action + "：" + detail;
        return new Activity(display, detail);
    }

    private String fallbackAction(String toolName) {
        try {
            ToolCallback callback = toolCallbackResolver.resolve(toolName);
            if (callback != null) {
                String description = callback.getToolDefinition().description();
                if (description != null && !description.isBlank()) {
                    String first = description.split("[。；;\\n]", 2)[0].trim();
                    if (!first.isEmpty()) {
                        return first.length() <= 18 ? first : first.substring(0, 18) + "…";
                    }
                }
            }
        }
        catch (RuntimeException e) {
            log.debug("读取工具描述失败：{}", e.getMessage());
        }
        return toolName;
    }

    /** 从入参 JSON 里挑一个对人最有信息量的值当摘要。 */
    private String detail(String arguments) {
        if (arguments == null || arguments.isBlank()) {
            return null;
        }
        try {
            JsonNode root = objectMapper.readTree(arguments);
            if (!root.isObject()) {
                return truncate(arguments);
            }
            for (String key : DETAIL_KEYS) {
                JsonNode value = root.get(key);
                if (value != null && value.isValueNode() && !value.asText().isBlank()) {
                    return truncate(value.asText());
                }
            }
            // 没有命中的字段：取第一个非空标量值
            for (JsonNode value : root) {
                if (value.isValueNode() && !value.asText().isBlank()) {
                    return truncate(value.asText());
                }
            }
        }
        catch (Exception e) {
            return truncate(arguments);
        }
        return null;
    }

    private static String truncate(String text) {
        String flat = text.replaceAll("\\s+", " ").trim();
        if (flat.isEmpty()) {
            return null;
        }
        return flat.length() <= DETAIL_MAX_CHARS ? flat : flat.substring(0, DETAIL_MAX_CHARS) + "…";
    }

    private static Map<String, String> actionWords() {
        Map<String, String> words = new LinkedHashMap<>();
        // 时间
        words.put("getCurrentTime", "查看当前时间");
        // 联网搜索
        words.put("webSearch", "联网搜索");
        words.put("searchWeb", "联网搜索");
        // 待办
        words.put("listTodayTodos", "读取今日待办");
        words.put("listTodosByDate", "读取指定日期的待办");
        words.put("listTodos", "读取待办");
        words.put("createTodo", "创建待办");
        words.put("updateTodo", "修改待办");
        words.put("completeTodo", "完成待办");
        words.put("deferTodo", "推迟待办");
        words.put("deleteTodo", "删除待办");
        words.put("getTodoStatistics", "统计待办");
        words.put("listOverdueTodos", "查找逾期待办");
        // 常用网站
        words.put("listSiteFolders", "读取网站分类");
        words.put("listSiteBookmarks", "读取常用网站");
        words.put("addSiteBookmark", "添加常用网站");
        words.put("updateSiteBookmark", "修改常用网站");
        words.put("deleteSiteBookmark", "删除常用网站");
        words.put("createSiteFolder", "新建网站分类");
        words.put("updateSiteFolder", "修改网站分类");
        words.put("deleteSiteFolder", "删除网站分类");
        // 长期记忆
        words.put("rememberUserMemory", "记住这条信息");
        words.put("recallUserMemory", "回忆你的档案");
        words.put("listUserMemories", "翻阅你的档案");
        words.put("forgetUserMemory", "忘掉某条记忆");
        words.put("deleteUserMemory", "删除某条记忆");
        return Map.copyOf(words);
    }

    /** 工具的展示描述。 */
    public record Activity(String display, String detail) {
    }
}

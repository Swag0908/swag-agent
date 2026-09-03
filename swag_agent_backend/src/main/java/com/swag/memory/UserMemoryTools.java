package com.swag.memory;

import org.springframework.ai.chat.model.ToolContext;
import org.springframework.ai.tool.annotation.Tool;
import org.springframework.ai.tool.annotation.ToolParam;
import org.springframework.stereotype.Component;

/**
 * 供大模型显式调用的「用户长期记忆」工具。
 * <p>
 * 只保存用户主动要求记住的精炼偏好/事实（ChatGPT Memory 的显式模式），
 * 不自动提炼、不保存一次性任务内容。
 */
@Component
public class UserMemoryTools {

    private final UserMemoryService service;

    public UserMemoryTools(UserMemoryService service) {
        this.service = service;
    }

    private Long userId(ToolContext context) {
        Object value = context.getContext().get("userId");
        if (value instanceof Number number) {
            return number.longValue();
        }
        if (value instanceof String text && !text.isBlank()) {
            return Long.parseLong(text);
        }
        throw new IllegalStateException("未登录，无法保存记忆");
    }

    @Tool(description = """
            当用户明确要求你「长期记住」某个偏好、身份或事实时调用，
            例如“记住我每周五下午开会”“以后都用表格回复我”“我的团队叫星火”。
            只保存用户主动要求记住的精炼一句话事实，不要自动归纳或保存一次性任务。
            记忆会跨会话生效，并可在「我的记忆」里查看或删除。""")
    public String rememberUserMemory(
            @ToolParam(description = "要长期记住的一句精炼事实/偏好，写成陈述句，例如「用户偏好用 Markdown 表格回复」") String content,
            ToolContext toolContext) {
        Long uid = userId(toolContext);
        if (!service.isEnabled(uid)) {
            return "长期记忆功能当前处于关闭状态，无法保存。请告知用户在「我的记忆」设置里开启后再试。";
        }
        UserMemoryDO memory = service.remember(uid, content);
        return "已记住：" + memory.getContent();
    }
}

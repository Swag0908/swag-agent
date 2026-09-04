package com.swag.todo;

import org.springframework.ai.chat.model.ToolContext;
import org.springframework.ai.tool.annotation.Tool;
import org.springframework.ai.tool.annotation.ToolParam;
import org.springframework.stereotype.Component;

import java.time.LocalDate;
import java.util.List;

/**
 * 供大模型调用的待办工具。用户身份通过 ToolContext 注入，避免依赖 ThreadLocal。
 */
@Component
public class TodoTools {

    private final TodoService service;

    public TodoTools(TodoService service) {
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
        throw new IllegalStateException("未登录，无法操作待办");
    }

    @Tool(description = "查询当前用户今日的待办清单，返回每条的 #id、标题、状态，"
            + "后续 completeTodo/deferTodo/deleteTodo 请按 #id 引用")
    public String listTodayTodos(ToolContext toolContext) {
        return format(service.listToday(userId(toolContext)), "今日待办");
    }

    @Tool(description = "新增一条待办。title 简短，note 放细节可为空；"
            + "dueDate 格式 yyyy-MM-dd，默认今天，也支持「明天」；dueTime 格式 HH:mm 可为空")
    public String createTodo(
            @ToolParam(description = "待办标题") String title,
            @ToolParam(description = "备注/细节，可为空") String note,
            @ToolParam(description = "目标日期 yyyy-MM-dd 或「明天」，可为空，默认今天") String dueDate,
            @ToolParam(description = "截止时间 HH:mm，可为空") String dueTime,
            ToolContext toolContext) {
        Long uid = userId(toolContext);
        TodoItemDO item = service.create(uid, title, note,
                service.parseDate(dueDate, TodoDates.today()),
                service.parseTime(dueTime),
                "CHAT");
        return "已记录待办 #" + item.getId() + " " + item.getTitle();
    }

    @Tool(description = "修改已有待办的标题、备注、日期或时间。"
            + " dueDate 格式 yyyy-MM-dd；dueTime 格式 HH:mm，不需要具体时间时留空")
    public String updateTodo(
            @ToolParam(description = "待办的 #id 或标题") String idOrTitle,
            @ToolParam(description = "修改后的完整标题") String title,
            @ToolParam(description = "修改后的备注，可为空") String note,
            @ToolParam(description = "修改后的日期 yyyy-MM-dd") String dueDate,
            @ToolParam(description = "修改后的时间 HH:mm，可为空") String dueTime,
            ToolContext toolContext) {
        TodoItemDO item = service.update(userId(toolContext), idOrTitle, title, note,
                service.parseDate(dueDate, null), service.parseTime(dueTime));
        return "已修改待办 #" + item.getId() + " " + item.getTitle()
                + " → " + item.getDueDate()
                + (item.getDueTime() == null ? "" : " " + item.getDueTime());
    }

    @Tool(description = "把一条待办标记为已完成。idOrTitle 传 #id 或标题")
    public String completeTodo(
            @ToolParam(description = "待办的 #id 或标题") String idOrTitle,
            ToolContext toolContext) {
        TodoItemDO item = service.complete(userId(toolContext), idOrTitle);
        return "已完成 #" + item.getId() + " " + item.getTitle();
    }

    @Tool(description = "把一条待办延期到新日期。newDate 格式 yyyy-MM-dd，也支持「明天」")
    public String deferTodo(
            @ToolParam(description = "待办的 #id 或标题") String idOrTitle,
            @ToolParam(description = "目标日期 yyyy-MM-dd 或「明天」") String newDate,
            ToolContext toolContext) {
        TodoItemDO item = service.defer(userId(toolContext), idOrTitle,
                service.parseDate(newDate, TodoDates.tomorrow()));
        return "已延期 #" + item.getId() + " " + item.getTitle() + " → " + item.getDueDate();
    }

    @Tool(description = "删除一条待办。idOrTitle 传 #id 或标题")
    public String deleteTodo(
            @ToolParam(description = "待办的 #id 或标题") String idOrTitle,
            ToolContext toolContext) {
        TodoItemDO item = service.delete(userId(toolContext), idOrTitle);
        return "已删除 #" + item.getId() + " " + item.getTitle();
    }

    @Tool(description = "查询指定日期的待办。date 格式 yyyy-MM-dd")
    public String listTodosByDate(
            @ToolParam(description = "日期 yyyy-MM-dd") String date,
            ToolContext toolContext) {
        LocalDate day = service.parseDate(date, TodoDates.today());
        return format(service.listByDate(userId(toolContext), day), day + " 待办");
    }

    private String format(List<TodoItemDO> items, String header) {
        if (items == null || items.isEmpty()) {
            return header + "：暂无。";
        }
        StringBuilder sb = new StringBuilder(header).append("（共 ").append(items.size()).append(" 条）：\n");
        for (TodoItemDO item : items) {
            sb.append("#").append(item.getId())
                    .append(" [").append("DONE".equals(item.getStatus()) ? "已完成" : "待办").append("] ")
                    .append(item.getTitle());
            if (item.getDueTime() != null) {
                sb.append("（截止 ").append(item.getDueTime()).append("）");
            }
            if (item.getNote() != null) {
                sb.append(" 备注：").append(item.getNote());
            }
            sb.append("\n");
        }
        return sb.toString().trim();
    }
}

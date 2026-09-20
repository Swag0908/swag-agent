package com.swag.notes;

import org.springframework.ai.chat.model.ToolContext;
import org.springframework.ai.tool.annotation.Tool;
import org.springframework.ai.tool.annotation.ToolParam;
import org.springframework.stereotype.Component;

import java.util.List;

/** 允许聊天 Agent 把启动机器上的 Markdown 文件导入当前用户自己的笔记库。 */
@Component
public class NotesTools {

    private final NotesImportService importService;

    public NotesTools(NotesImportService importService) {
        this.importService = importService;
    }

    @Tool(description = "把运行本项目的机器上的一个或多个本地 .md 文件导入当前用户的 Markdown 笔记。"
            + "sourcePaths 必须是用户给出的绝对路径，且位于服务端配置允许的导入目录中；"
            + "会复制 Markdown 引用的本地图片、脚本和附件并改写链接。"
            + "targetFolder 是笔记库中已存在的目标文件夹，用户未指定时传「未分类」。"
            + "同名笔记不会覆盖，会自动加 (1)、(2) 后缀。")
    public String importLocalMarkdownNotes(
            @ToolParam(description = "要导入的本地 .md 绝对路径列表") List<String> sourcePaths,
            @ToolParam(description = "笔记库内的目标文件夹路径；未指定时传「未分类」") String targetFolder,
            ToolContext toolContext) {
        NotesViews.ImportResult result = importService.importLocal(
                userId(toolContext), sourcePaths, targetFolder);
        StringBuilder message = new StringBuilder();
        if (!result.imported().isEmpty()) {
            message.append("已导入 ").append(result.imported().size()).append(" 篇笔记：")
                    .append(String.join("、", result.imported()))
                    .append("；复制附件 ").append(result.attachmentsCopied()).append(" 个。");
        }
        if (!result.failed().isEmpty()) {
            if (!message.isEmpty()) message.append('\n');
            message.append("导入失败 ").append(result.failed().size()).append(" 个：");
            for (NotesViews.ImportFailure failure : result.failed()) {
                message.append("\n- ").append(failure.source()).append("：").append(failure.reason());
            }
        }
        if (!result.warnings().isEmpty()) {
            if (!message.isEmpty()) message.append('\n');
            message.append("附件提示：");
            for (String warning : result.warnings()) {
                message.append("\n- ").append(warning);
            }
        }
        return message.isEmpty() ? "没有可导入的 Markdown 文件。" : message.toString();
    }

    private Long userId(ToolContext context) {
        Object value = context.getContext().get("userId");
        if (value instanceof Number number) {
            return number.longValue();
        }
        if (value instanceof String text && !text.isBlank()) {
            return Long.parseLong(text);
        }
        throw new IllegalStateException("未登录，无法导入 Markdown 笔记");
    }
}

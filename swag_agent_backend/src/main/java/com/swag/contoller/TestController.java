package com.swag.contoller;

import com.swag.audit.context.AuditContextHolder;
import com.swag.auth.UserContextHolder;
import com.swag.tool.SelectModelTool;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import reactor.core.publisher.Flux;

import java.util.Map;

@RestController
@RequestMapping("test")
public class TestController {
    @Autowired
    private SelectModelTool selectModelTool;

    private static final String SYSTEM_PROMPT = """
            你是 swag_agent 助手。可用工具：getCurrentTime（查时间）、todo 系列（管理待办）、webSearch（联网搜索）、
            常用网站系列（管理当前用户自己的常用网站菜单，均为用户维度：listSiteFolders 查分类、listSiteBookmarks 查网站、
            addSiteBookmark 添加网站、updateSiteBookmark 修改网站、deleteSiteBookmark 删除网站、
            createSiteFolder 新建分类、updateSiteFolder 重命名/移动分类、deleteSiteFolder 删除分类）。
            添加网站时若分类不存在或含义相近，先向用户确认是新建还是放入相近分类，得到同意后再操作；删除前先征得用户确认。
            规则：当用户的问题涉及实时或时效性信息、需要最新数据，或你对答案不确定时，必须先调用 webSearch 联网搜索，再基于搜索结果回答，并尽量附上来源链接；不要凭空编造。
            """;

    /**
     * 测试聊天接口
     * @param model
     * @param userInput
     * @return
     */
    @GetMapping("/chat")
    public String chat(@RequestParam(value = "model",defaultValue = "1") Integer model,@RequestParam(value = "userInput") String userInput) {
        ChatClient chatClient = selectModelTool.selectModel(model);
        return chatClient.prompt().system(SYSTEM_PROMPT).user(userInput)
                .toolContext(toolContext())
                .call().content();
    }

    /**
     * 流式聊天接口：返回纯文本流（逐字输出），前端通过 Vite 代理读取。
     * @param model
     * @param userInput
     * @return
     */
    @GetMapping(value = "/chat/stream", produces = MediaType.TEXT_PLAIN_VALUE)
    public Flux<String> chatStream(@RequestParam(value = "model", defaultValue = "1") Integer model,
                                   @RequestParam(value = "userInput") String userInput) {
        ChatClient chatClient = selectModelTool.selectModel(model);
        Flux<String> content = chatClient.prompt().system(SYSTEM_PROMPT).user(userInput)
                .toolContext(toolContext())
                .stream().content()
                .onErrorResume(e -> Flux.just("\n\n[错误] " + e.getMessage()));
        return AuditContextHolder.propagate(content);
    }

    /**
     * 把登录用户 ID 通过 ToolContext 注入工具，避免流式调用下 ThreadLocal 失效。
     */
    private Map<String, Object> toolContext() {
        Long userId = UserContextHolder.currentUserId();
        return userId == null ? Map.of() : Map.of("userId", userId);
    }

}

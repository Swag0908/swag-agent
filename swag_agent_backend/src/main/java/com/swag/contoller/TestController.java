package com.swag.contoller;

import com.swag.audit.context.AuditContextHolder;
import com.swag.auth.UserContextHolder;
import com.swag.chat.ChatConversationDO;
import com.swag.chat.ChatHistoryRepository;
import com.swag.memory.UserMemoryService;
import com.swag.tool.SelectModelTool;
import org.springframework.ai.chat.client.ChatClient;
import org.springframework.ai.chat.memory.ChatMemory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;
import reactor.core.publisher.Flux;

import java.time.LocalDateTime;
import java.util.List;
import java.util.Map;

@RestController
@RequestMapping("test")
public class TestController {
    @Autowired
    private SelectModelTool selectModelTool;

    @Autowired
    private ChatHistoryRepository chatHistoryRepository;

    @Autowired
    private UserMemoryService userMemoryService;

    private static final String SYSTEM_PROMPT = """
            你是 swag_agent 助手。可用工具：getCurrentTime（查时间）、todo 系列（管理待办）、webSearch（联网搜索）、
            常用网站系列（管理当前用户自己的常用网站菜单，均为用户维度：listSiteFolders 查分类、listSiteBookmarks 查网站、
            addSiteBookmark 添加网站、updateSiteBookmark 修改网站、deleteSiteBookmark 删除网站、
            createSiteFolder 新建分类、updateSiteFolder 重命名/移动分类、deleteSiteFolder 删除分类）、
            rememberUserMemory（用户明确要求长期记住偏好/事实时调用，例如「记住我每周五下午开会」）。
            添加网站时若分类不存在或含义相近，先向用户确认是新建还是放入相近分类，得到同意后再操作；删除前先征得用户确认。
            规则：当用户的问题涉及实时或时效性信息、需要最新数据，或你对答案不确定时，必须先调用 webSearch 联网搜索，再基于搜索结果回答，并尽量附上来源链接；不要凭空编造。
            """;

    /**
     * 测试聊天接口（非流式）
     * @param model
     * @param userInput
     * @param conversationId 历史会话 id；提供后该轮对话写入会话历史，记忆按会话隔离
     * @return
     */
    @GetMapping("/chat")
    public String chat(@RequestParam(value = "model", defaultValue = "1") Integer model,
                       @RequestParam(value = "userInput") String userInput,
                       @RequestParam(value = "conversationId", required = false) Long conversationId) {
        Long userId = UserContextHolder.currentUserId();
        ChatConversationDO conversation = resolveConversation(conversationId, userId);
        ChatClient chatClient = selectModelTool.selectModel(model);
        String answer = chatClient.prompt().system(buildSystemPrompt(userId, userInput)).user(userInput)
                .advisors(a -> a.param(ChatMemory.CONVERSATION_ID, memoryConversationId(conversationId, userId)))
                .toolContext(toolContext())
                .call().content();
        if (conversation != null) {
            persistExchange(conversation, userId, userInput, answer == null ? "" : answer);
        }
        return answer;
    }

    /**
     * 流式聊天接口：返回纯文本流（逐字输出），前端通过 Vite 代理读取。
     * 对话记忆由 ChatClient 的默认 Advisor 自动处理：
     * 短期 = MessageChatMemoryAdvisor（最近 N 条逐字回放），长期 = VectorStoreChatMemoryAdvisor（pgvector 语义召回）。
     * 提供 conversationId 时二者按会话 id 隔离，同时把本轮用户提问与助手回复持久化到会话历史表。
     * @param model
     * @param userInput
     * @param conversationId 历史会话 id（可选）；缺省时保持旧行为（按用户 ID 一条记忆线，不写会话历史）
     * @return
     */
    @GetMapping(value = "/chat/stream", produces = MediaType.TEXT_PLAIN_VALUE)
    public Flux<String> chatStream(@RequestParam(value = "model", defaultValue = "1") Integer model,
                                   @RequestParam(value = "userInput") String userInput,
                                   @RequestParam(value = "conversationId", required = false) Long conversationId) {
        Long userId = UserContextHolder.currentUserId();
        ChatConversationDO conversation = resolveConversation(conversationId, userId);
        ChatClient chatClient = selectModelTool.selectModel(model);

        LocalDateTime startedAt = LocalDateTime.now();
        // 用户提问先落库（含自动标题），保证会话列表立即出现、首问即生成标题
        if (conversation != null) {
            persistUserMessage(conversation, userId, userInput, startedAt);
        }

        StringBuilder buffer = new StringBuilder();
        Flux<String> content = chatClient.prompt().system(buildSystemPrompt(userId, userInput)).user(userInput)
                .advisors(a -> a.param(ChatMemory.CONVERSATION_ID, memoryConversationId(conversationId, userId)))
                .toolContext(toolContext())
                .stream().content()
                .doOnNext(buffer::append)
                .onErrorResume(e -> {
                    String errorText = "\n\n[错误] " + e.getMessage();
                    buffer.append(errorText);
                    return Flux.just(errorText);
                })
                .doFinally(signal -> {
                    // 正常结束、中途停止都尽量保存已生成内容（含错误提示文本），避免重开会话时对不上
                    if (conversation != null) {
                        String full = buffer.toString();
                        if (!full.isBlank()) {
                            chatHistoryRepository.insertMessage(conversation.getId(), userId,
                                    "assistant", full, LocalDateTime.now());
                        }
                        chatHistoryRepository.touchConversation(conversation.getId(), LocalDateTime.now());
                    }
                });
        return AuditContextHolder.propagate(content);
    }

    /**
     * 系统提示 = 固定工具说明 + 每轮按当前提问语义召回的「用户长期记忆档案」。
     * 记忆按 userId 跨会话召回（ChatGPT Memory 式），不包含会话内的短期上下文。
     */
    private String buildSystemPrompt(Long userId, String userInput) {
        List<String> memories = userMemoryService.recall(userId, userInput);
        if (memories.isEmpty()) {
            return SYSTEM_PROMPT;
        }
        StringBuilder sb = new StringBuilder(SYSTEM_PROMPT);
        sb.append("\n\n【该用户的长期记忆档案（用户此前主动要求记住的偏好/事实；")
           .append("若与当前问题相关请据此作答，不相关可忽略；不要把这些当作对话历史）】\n");
        for (int i = 0; i < memories.size(); i++) {
            sb.append(i + 1).append(". ").append(memories.get(i)).append('\n');
        }
        return sb.toString();
    }

    /**
     * 校验会话归属：conversationId 为空时返回 null（保持旧用户级记忆线行为）；
     * 非空但查不到或不属于当前用户则抛 404。
     */
    private ChatConversationDO resolveConversation(Long conversationId, Long userId) {
        if (conversationId == null) {
            return null;
        }
        if (userId == null) {
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "未登录");
        }
        return chatHistoryRepository.findConversation(conversationId, userId)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "会话不存在"));
    }

    private void persistUserMessage(ChatConversationDO conversation, Long userId,
                                    String userInput, LocalDateTime now) {
        chatHistoryRepository.insertMessage(conversation.getId(), userId, "user", userInput, now);
        chatHistoryRepository.updateTitleIfEmpty(conversation.getId(), autoTitle(userInput), now);
        // 标题已存在时 updateTitleIfEmpty 不生效，这里无条件刷新会话时间
        chatHistoryRepository.touchConversation(conversation.getId(), now);
    }

    private void persistExchange(ChatConversationDO conversation, Long userId,
                                 String userInput, String assistantContent, LocalDateTime now) {
        // 非流式接口：先落用户消息与标题，再落助手回复
        LocalDateTime base = now == null ? LocalDateTime.now() : now;
        persistUserMessage(conversation, userId, userInput, base);
        if (assistantContent != null && !assistantContent.isBlank()) {
            chatHistoryRepository.insertMessage(conversation.getId(), userId, "assistant",
                    assistantContent, base);
        }
        chatHistoryRepository.touchConversation(conversation.getId(), base);
    }

    private void persistExchange(ChatConversationDO conversation, Long userId,
                                 String userInput, String assistantContent) {
        persistExchange(conversation, userId, userInput, assistantContent, null);
    }

    /** 标题：压缩空白后取前 40 个字。 */
    private String autoTitle(String text) {
        String flat = (text == null ? "" : text).replaceAll("\\s+", " ").trim();
        return flat.length() <= 40 ? flat : flat.substring(0, 40) + "…";
    }

    /**
     * 记忆按会话隔离：有会话 id 用会话 id；否则退回旧行为（同登录用户 = 同一条对话线）。
     */
    private String memoryConversationId(Long conversationId, Long userId) {
        if (conversationId != null) {
            return conversationId.toString();
        }
        return userId == null ? "anonymous" : userId.toString();
    }

    /**
     * 把登录用户 ID 通过 ToolContext 注入工具，避免流式调用下 ThreadLocal 失效。
     */
    private Map<String, Object> toolContext() {
        Long userId = UserContextHolder.currentUserId();
        return userId == null ? Map.of() : Map.of("userId", userId);
    }

}

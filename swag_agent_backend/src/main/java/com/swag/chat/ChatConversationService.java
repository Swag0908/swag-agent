package com.swag.chat;

import com.swag.audit.core.AuditConversationRepository;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.ai.chat.memory.ChatMemory;
import org.springframework.ai.chat.messages.AssistantMessage;
import org.springframework.ai.chat.messages.Message;
import org.springframework.ai.chat.messages.UserMessage;
import org.springframework.ai.document.Document;
import org.springframework.ai.vectorstore.VectorStore;
import org.springframework.ai.vectorstore.filter.FilterExpressionBuilder;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Objects;

/**
 * 会话生命周期管理：统一处理历史记录、短期记忆、向量记忆和审计记录的清理与重建。
 *
 * <p>三层存储各管一段，删除会话时必须一起清理，否则用户删掉的对话会在下一轮被模型「想起来」：
 * <ul>
 *   <li>{@code chat_conversation} / {@code chat_message}：界面上看到的历史原文</li>
 *   <li>{@code SPRING_AI_CHAT_MEMORY}（短期记忆，逐字回放最近 N 条）</li>
 *   <li>pgvector 的 {@code vector_store}（长期语义记忆，按语义召回历史片段）</li>
 * </ul>
 * 另外 {@code audit_event} 会把聊天请求的输入输出记进审计表，会话删除时一并回收。
 */
@Service
public class ChatConversationService {

    private static final Logger log = LoggerFactory.getLogger(ChatConversationService.class);

    /** 与 MessageWindowChatMemory 的窗口一致，避免重建时写入超出窗口的历史。 */
    private static final int MEMORY_WINDOW = 40;

    private static final String ROLE_USER = "user";
    private static final String ROLE_ASSISTANT = "assistant";

    private final ChatHistoryRepository repository;
    private final ChatMemory chatMemory;
    private final VectorStore vectorStore;
    private final AuditConversationRepository auditConversationRepository;

    public ChatConversationService(ChatHistoryRepository repository, ChatMemory chatMemory,
                                   VectorStore vectorStore,
                                   AuditConversationRepository auditConversationRepository) {
        this.repository = repository;
        this.chatMemory = chatMemory;
        this.vectorStore = vectorStore;
        this.auditConversationRepository = auditConversationRepository;
    }

    /**
     * 只删除属于该用户的会话。历史主记录删除成功后，再尽力清理辅助存储，
     * 避免外部向量库暂时不可用时让用户无法删除会话。
     */
    public boolean delete(Long userId, Long conversationId) {
        if (!repository.deleteConversation(conversationId, userId)) {
            return false;
        }
        clearAssistantMemory(conversationId);
        deleteAuditEvents(conversationId);
        return true;
    }

    /** 清空当前用户的全部历史会话，并回收对应的记忆与审计记录。 */
    public int clearAll(Long userId) {
        List<Long> deletedIds = repository.deleteAllConversations(userId);
        for (Long conversationId : deletedIds) {
            clearAssistantMemory(conversationId);
            deleteAuditEvents(conversationId);
        }
        log.info("用户 {} 清空了 {} 个历史会话", userId, deletedIds.size());
        return deletedIds.size();
    }

    /**
     * 删除会话里的一条消息，并把与它配对的那条一起删掉（用户提问 + 紧随其后的助手回复），
     * 删完对话仍然一问一答成对，不会留下孤立的半截内容。
     *
     * <p>删除后按剩余消息重建该会话的记忆窗口：短期记忆重放最近 {@value #MEMORY_WINDOW} 条，
     * 向量记忆重新写入剩余消息，保证模型不会继续提起被删掉的内容。
     *
     * @return 删除后该会话剩余的消息（按时间正序）
     */
    public List<ChatMessageDO> deleteMessagePair(Long userId, Long conversationId, Long messageId) {
        List<ChatMessageDO> all = repository.listMessages(conversationId);
        int index = indexOfMessage(all, messageId);
        if (index < 0) {
            throw new IllegalArgumentException("消息不存在");
        }

        List<Long> pairIds = pairedMessageIds(all, index);
        int deleted = repository.deleteMessages(conversationId, userId, pairIds);
        if (deleted == 0) {
            throw new IllegalArgumentException("消息不存在或不属于当前用户");
        }

        List<ChatMessageDO> remaining = all.stream()
                .filter(message -> !pairIds.contains(message.getId()))
                .toList();
        rebuildMemory(conversationId, remaining);
        return remaining;
    }

    private static int indexOfMessage(List<ChatMessageDO> messages, Long messageId) {
        for (int i = 0; i < messages.size(); i++) {
            if (messages.get(i).getId().equals(messageId)) {
                return i;
            }
        }
        return -1;
    }

    /**
     * 找出与目标消息配对的 id 集合：目标是提问就带上紧随的回答，
     * 目标是回答就带上紧邻的提问（成对边界由 user 消息划定）。
     */
    private static List<Long> pairedMessageIds(List<ChatMessageDO> messages, int index) {
        List<Long> ids = new ArrayList<>();
        ids.add(messages.get(index).getId());
        if (ROLE_USER.equals(messages.get(index).getRole())) {
            if (index + 1 < messages.size() && ROLE_ASSISTANT.equals(messages.get(index + 1).getRole())) {
                ids.add(messages.get(index + 1).getId());
            }
        }
        else if (index > 0 && ROLE_USER.equals(messages.get(index - 1).getRole())) {
            ids.add(messages.get(index - 1).getId());
        }
        return ids;
    }

    /** 清掉短期记忆与向量记忆。删除会话、重建记忆前都会先走这一步。 */
    private void clearAssistantMemory(Long conversationId) {
        String memoryId = conversationId.toString();
        try {
            chatMemory.clear(memoryId);
        }
        catch (RuntimeException e) {
            log.warn("会话 {} 的短期记忆清理失败", conversationId, e);
        }
        try {
            vectorStore.delete(new FilterExpressionBuilder()
                    .eq("conversationId", memoryId)
                    .build());
        }
        catch (RuntimeException e) {
            log.warn("会话 {} 的向量记忆清理失败", conversationId, e);
        }
    }

    /**
     * 用剩余消息重建该会话的两层记忆。
     *
     * <p>两层都是「先清空再重放」，比按内容匹配去删单条更可靠——向量库里的文档 id 是随机 UUID，
     * 没有跟 chat_message.id 建立映射，想精确删某一条只能靠重放。
     * 这里的失败只记日志不抛错：消息本身已经从历史里删掉了，记忆重建失败不该让删除操作看起来失败。
     */
    private void rebuildMemory(Long conversationId, List<ChatMessageDO> remaining) {
        String memoryId = conversationId.toString();
        clearAssistantMemory(conversationId);

        List<Message> window = remaining.stream()
                .map(ChatConversationService::toSpringAiMessage)
                .filter(Objects::nonNull)
                .toList();
        if (window.isEmpty()) {
            return;
        }
        // 只回放最近 MEMORY_WINDOW 条，与 MessageChatMemoryAdvisor 的窗口保持一致
        if (window.size() > MEMORY_WINDOW) {
            window = List.copyOf(window.subList(window.size() - MEMORY_WINDOW, window.size()));
        }

        try {
            chatMemory.add(memoryId, window);
        }
        catch (RuntimeException e) {
            log.warn("会话 {} 的短期记忆重建失败", conversationId, e);
        }

        try {
            List<Document> documents = window.stream()
                    .map(message -> Document.builder()
                            .text(message.getText())
                            // 元数据键必须与 VectorStoreChatMemoryAdvisor 写入时保持一致，
                            // 否则召回时按 conversationId 过滤就查不到重建的文档
                            .metadata(Map.of(
                                    "conversationId", memoryId,
                                    "messageType", message.getMessageType().name()))
                            .build())
                    .toList();
            vectorStore.add(documents);
        }
        catch (RuntimeException e) {
            log.warn("会话 {} 的向量记忆重建失败", conversationId, e);
        }
    }

    private static Message toSpringAiMessage(ChatMessageDO message) {
        if (message.getContent() == null || message.getContent().isBlank()) {
            return null;
        }
        if (ROLE_USER.equals(message.getRole())) {
            return new UserMessage(message.getContent());
        }
        if (ROLE_ASSISTANT.equals(message.getRole())) {
            return new AssistantMessage(message.getContent());
        }
        return null;
    }

    private void deleteAuditEvents(Long conversationId) {
        try {
            int removed = auditConversationRepository.deleteByConversationId(conversationId.toString());
            if (removed > 0) {
                log.info("已回收会话 {} 的 {} 条审计记录", conversationId, removed);
            }
        }
        catch (RuntimeException e) {
            log.warn("会话 {} 的审计记录清理失败", conversationId, e);
        }
    }
}

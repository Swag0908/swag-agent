package com.swag.chat;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.ai.chat.memory.ChatMemory;
import org.springframework.ai.vectorstore.VectorStore;
import org.springframework.ai.vectorstore.filter.FilterExpressionBuilder;
import org.springframework.stereotype.Service;

/**
 * 会话生命周期管理：统一处理历史记录、短期记忆和向量记忆的清理。
 */
@Service
public class ChatConversationService {

    private static final Logger log = LoggerFactory.getLogger(ChatConversationService.class);

    private final ChatHistoryRepository repository;
    private final ChatMemory chatMemory;
    private final VectorStore vectorStore;

    public ChatConversationService(ChatHistoryRepository repository, ChatMemory chatMemory,
                                   VectorStore vectorStore) {
        this.repository = repository;
        this.chatMemory = chatMemory;
        this.vectorStore = vectorStore;
    }

    /**
     * 只删除属于该用户的会话。历史主记录删除成功后，再尽力清理辅助记忆存储，
     * 避免外部向量库暂时不可用时让用户无法删除会话。
     */
    public boolean delete(Long userId, Long conversationId) {
        if (!repository.deleteConversation(conversationId, userId)) {
            return false;
        }

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
        return true;
    }
}

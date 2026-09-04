package com.swag.chat;

import org.junit.jupiter.api.Test;
import org.springframework.ai.chat.memory.ChatMemory;
import org.springframework.ai.vectorstore.VectorStore;
import org.springframework.ai.vectorstore.filter.Filter;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class ChatConversationServiceTests {

    @Test
    void deletingOwnedConversationAlsoClearsItsAssistantMemory() {
        ChatHistoryRepository repository = mock(ChatHistoryRepository.class);
        ChatMemory chatMemory = mock(ChatMemory.class);
        VectorStore vectorStore = mock(VectorStore.class);
        when(repository.deleteConversation(42L, 7L)).thenReturn(true);
        ChatConversationService service = new ChatConversationService(repository, chatMemory, vectorStore);

        boolean deleted = service.delete(7L, 42L);

        assertThat(deleted).isTrue();
        verify(chatMemory).clear("42");
        verify(vectorStore).delete(any(Filter.Expression.class));
    }

    @Test
    void missingOrForeignConversationDoesNotClearMemory() {
        ChatHistoryRepository repository = mock(ChatHistoryRepository.class);
        ChatMemory chatMemory = mock(ChatMemory.class);
        VectorStore vectorStore = mock(VectorStore.class);
        when(repository.deleteConversation(42L, 7L)).thenReturn(false);
        ChatConversationService service = new ChatConversationService(repository, chatMemory, vectorStore);

        boolean deleted = service.delete(7L, 42L);

        assertThat(deleted).isFalse();
        verify(chatMemory, never()).clear(any());
        verify(vectorStore, never()).delete(any(Filter.Expression.class));
    }
}

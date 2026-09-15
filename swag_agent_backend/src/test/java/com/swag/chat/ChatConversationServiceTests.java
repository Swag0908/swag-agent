package com.swag.chat;

import com.swag.audit.core.AuditConversationRepository;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.ai.chat.memory.ChatMemory;
import org.springframework.ai.chat.messages.Message;
import org.springframework.ai.chat.messages.MessageType;
import org.springframework.ai.document.Document;
import org.springframework.ai.vectorstore.VectorStore;
import org.springframework.ai.vectorstore.filter.Filter;

import java.time.LocalDateTime;
import java.util.List;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.anyList;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class ChatConversationServiceTests {

    private final ChatHistoryRepository repository = mock(ChatHistoryRepository.class);
    private final ChatMemory chatMemory = mock(ChatMemory.class);
    private final VectorStore vectorStore = mock(VectorStore.class);
    private final AuditConversationRepository auditRepository = mock(AuditConversationRepository.class);
    private final ChatConversationService service =
            new ChatConversationService(repository, chatMemory, vectorStore, auditRepository);

    @Test
    void deletingOwnedConversationAlsoClearsItsAssistantMemory() {
        when(repository.deleteConversation(42L, 7L)).thenReturn(true);

        boolean deleted = service.delete(7L, 42L);

        assertThat(deleted).isTrue();
        verify(chatMemory).clear("42");
        verify(vectorStore).delete(any(Filter.Expression.class));
        verify(auditRepository).deleteByConversationId("42");
    }

    @Test
    void missingOrForeignConversationDoesNotClearMemory() {
        when(repository.deleteConversation(42L, 7L)).thenReturn(false);

        boolean deleted = service.delete(7L, 42L);

        assertThat(deleted).isFalse();
        verify(chatMemory, never()).clear(any());
        verify(vectorStore, never()).delete(any(Filter.Expression.class));
        verify(auditRepository, never()).deleteByConversationId(any());
    }

    @Test
    void deletingUserMessageAlsoDeletesThePairedAnswer() {
        stubMessages(message(1L, "user", "旧问题"),
                message(2L, "assistant", "旧回答"),
                message(3L, "user", "新问题"),
                message(4L, "assistant", "新回答"));
        when(repository.deleteMessages(eq(42L), eq(7L), anyList())).thenReturn(2);

        List<ChatMessageDO> remaining = service.deleteMessagePair(7L, 42L, 1L);

        assertThat(deletedIds()).containsExactlyInAnyOrder(1L, 2L);
        assertThat(remaining).extracting(ChatMessageDO::getId).containsExactly(3L, 4L);
    }

    @Test
    void deletingAssistantMessageAlsoDeletesThePairedQuestion() {
        stubMessages(message(1L, "user", "旧问题"),
                message(2L, "assistant", "旧回答"),
                message(3L, "user", "新问题"),
                message(4L, "assistant", "新回答"));
        when(repository.deleteMessages(eq(42L), eq(7L), anyList())).thenReturn(2);

        service.deleteMessagePair(7L, 42L, 4L);

        assertThat(deletedIds()).containsExactlyInAnyOrder(3L, 4L);
    }

    @Test
    void rebuildingMemoryReplaysOnlyRemainingMessages() {
        stubMessages(message(1L, "user", "旧问题"),
                message(2L, "assistant", "旧回答"),
                message(3L, "user", "新问题"));
        when(repository.deleteMessages(eq(42L), eq(7L), anyList())).thenReturn(2);

        service.deleteMessagePair(7L, 42L, 1L);

        // 先清空，避免被删内容继续留在模型上下文里
        verify(chatMemory).clear("42");
        ArgumentCaptor<List<Message>> captor = ArgumentCaptor.forClass(List.class);
        verify(chatMemory).add(eq("42"), captor.capture());
        List<Message> replayed = captor.getValue();
        assertThat(replayed).hasSize(1);
        assertThat(replayed.get(0).getText()).isEqualTo("新问题");
        assertThat(replayed.get(0).getMessageType()).isEqualTo(MessageType.USER);

        // 向量记忆同样重建，元数据键必须与 VectorStoreChatMemoryAdvisor 一致
        ArgumentCaptor<List<Document>> documents = ArgumentCaptor.forClass(List.class);
        verify(vectorStore).add(documents.capture());
        assertThat(documents.getValue()).hasSize(1);
        assertThat(documents.getValue().get(0).getMetadata())
                .containsEntry("conversationId", "42")
                .containsEntry("messageType", "USER");
        assertThat(documents.getValue().get(0).getText()).isEqualTo("新问题");
    }

    @Test
    void deletingUnknownMessageIsRejected() {
        stubMessages(message(1L, "user", "旧问题"));

        assertThatThrownBy(() -> service.deleteMessagePair(7L, 42L, 999L))
                .isInstanceOf(IllegalArgumentException.class);
        verify(repository, never()).deleteMessages(any(), any(), anyList());
    }

    @Test
    void clearingAllReclaimsMemoryAndAuditPerConversation() {
        when(repository.deleteAllConversations(7L)).thenReturn(List.of(11L, 12L));

        int cleared = service.clearAll(7L);

        assertThat(cleared).isEqualTo(2);
        verify(chatMemory).clear("11");
        verify(chatMemory).clear("12");
        verify(auditRepository).deleteByConversationId("11");
        verify(auditRepository).deleteByConversationId("12");
    }

    private void stubMessages(ChatMessageDO... messages) {
        when(repository.listMessages(42L)).thenReturn(List.of(messages));
    }

    private List<Long> deletedIds() {
        @SuppressWarnings("unchecked")
        ArgumentCaptor<List<Long>> captor = ArgumentCaptor.forClass(List.class);
        verify(repository).deleteMessages(eq(42L), eq(7L), captor.capture());
        return captor.getValue();
    }

    private static ChatMessageDO message(Long id, String role, String content) {
        ChatMessageDO message = new ChatMessageDO();
        message.setId(id);
        message.setConversationId(42L);
        message.setUserId(7L);
        message.setRole(role);
        message.setContent(content);
        message.setCreatedAt(LocalDateTime.now());
        return message;
    }
}

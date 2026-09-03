package com.swag.chat;

import com.swag.auth.UserContextHolder;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

import java.time.LocalDateTime;
import java.time.ZoneId;
import java.util.List;

/**
 * 历史会话 REST（DeepSeek 式工作区）。
 */
@RestController
@RequestMapping("/chat/conversations")
public class ChatConversationController {

    public record CreateRequest(String title) {
    }

    /** 会话列表项：时间用 epoch 毫秒返回，方便前端按本地日期分组（今天/昨天/更早）。 */
    public record ConversationResponse(Long id, String title, long createdAtMs, long updatedAtMs) {
        static ConversationResponse from(ChatConversationDO conv) {
            return new ConversationResponse(conv.getId(), conv.getTitle(),
                    toEpochMs(conv.getCreatedAt()), toEpochMs(conv.getUpdatedAt()));
        }
    }

    public record MessageResponse(Long id, String role, String content) {
        static MessageResponse from(ChatMessageDO msg) {
            return new MessageResponse(msg.getId(), msg.getRole(), msg.getContent());
        }
    }

    private final ChatHistoryRepository repository;

    public ChatConversationController(ChatHistoryRepository repository) {
        this.repository = repository;
    }

    @GetMapping
    public List<ConversationResponse> list() {
        return repository.listConversations(currentUser()).stream()
                .map(ConversationResponse::from)
                .toList();
    }

    /** 新建空会话；标题留空，等第一句提问到达后由聊天接口自动生成。 */
    @PostMapping
    public ConversationResponse create(@RequestBody(required = false) CreateRequest request) {
        String title = request == null ? "" : (request.title() == null ? "" : request.title());
        ChatConversationDO conv = repository.insertConversation(currentUser(), title, LocalDateTime.now());
        return ConversationResponse.from(conv);
    }

    @GetMapping("/{id}/messages")
    public List<MessageResponse> messages(@PathVariable Long id) {
        Long userId = currentUser();
        repository.findConversation(id, userId)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "会话不存在"));
        return repository.listMessages(id).stream()
                .map(MessageResponse::from)
                .toList();
    }

    private Long currentUser() {
        Long userId = UserContextHolder.currentUserId();
        if (userId == null) {
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "未登录");
        }
        return userId;
    }

    private static long toEpochMs(LocalDateTime time) {
        return time.atZone(ZoneId.systemDefault()).toInstant().toEpochMilli();
    }
}

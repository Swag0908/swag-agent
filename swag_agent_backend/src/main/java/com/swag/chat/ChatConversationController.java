package com.swag.chat;

import com.swag.auth.UserContextHolder;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

import java.time.LocalDateTime;
import java.time.ZoneId;
import java.util.List;

/**
 * 历史会话 REST（DeepSeek 式工作区）。
 *
 * <p>支持删除会话（连同聊天记录、记忆与审计记录一起回收）、收藏并备注会话、
 * 收藏区拖拽排序、删除会话内单条对话、清空全部历史会话。
 */
@RestController
@RequestMapping("/chat/conversations")
public class ChatConversationController {

    public record CreateRequest(String title) {
    }

    /** 收藏开关 + 备注名。favorite=false 时忽略 note。 */
    public record FavoriteRequest(Boolean favorite, String note) {
    }

    /** 收藏区拖拽后的完整顺序。 */
    public record FavoriteOrderRequest(List<Long> ids) {
    }

    /** 会话列表项：时间用 epoch 毫秒返回，方便前端按本地日期分组（今天/昨天/更早）。 */
    public record ConversationResponse(Long id, String title, boolean favorite, String favoriteNote,
                                       Integer favoriteOrder, long favoritedAtMs,
                                       long createdAtMs, long updatedAtMs) {
        static ConversationResponse from(ChatConversationDO conv) {
            return new ConversationResponse(conv.getId(), conv.getTitle(), conv.isFavorite(),
                    conv.getFavoriteNote(), conv.getFavoriteOrder(),
                    toEpochMs(conv.getFavoritedAt()),
                    toEpochMs(conv.getCreatedAt()), toEpochMs(conv.getUpdatedAt()));
        }
    }

    public record MessageResponse(Long id, String role, String content) {
        static MessageResponse from(ChatMessageDO msg) {
            return new MessageResponse(msg.getId(), msg.getRole(), msg.getContent());
        }
    }

    public record ClearResponse(int deleted) {
    }

    private final ChatHistoryRepository repository;
    private final ChatConversationService service;

    public ChatConversationController(ChatHistoryRepository repository, ChatConversationService service) {
        this.repository = repository;
        this.service = service;
    }

    /** 列表顺序由后端决定：收藏置顶（可手动排序），其余按最近活跃倒序。 */
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

    @DeleteMapping("/{id}")
    public void delete(@PathVariable Long id) {
        if (!service.delete(currentUser(), id)) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "会话不存在");
        }
    }

    /** 清空全部历史会话；返回清掉的会话数，供前端提示。 */
    @DeleteMapping
    public ClearResponse clear() {
        return new ClearResponse(service.clearAll(currentUser()));
    }

    /**
     * 收藏 / 取消收藏，并可同时设置备注名。新收藏默认排到收藏区末尾。
     */
    @PutMapping("/{id}/favorite")
    public ConversationResponse favorite(@PathVariable Long id, @RequestBody FavoriteRequest request) {
        if (request == null || request.favorite() == null) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "缺少 favorite 参数");
        }

        Long userId = currentUser();
        ChatConversationDO conv = repository.findConversation(id, userId)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "会话不存在"));

        boolean favorite = request.favorite();
        String note = normalizeNote(request.note());
        Integer order = favorite ? resolveFavoriteOrder(userId, conv) : null;

        if (!repository.setFavorite(id, userId, favorite, note, order, LocalDateTime.now())) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "会话不存在");
        }
        return repository.findConversation(id, userId)
                .map(ConversationResponse::from)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "会话不存在"));
    }

    /** 收藏区拖拽排序：按提交的 id 顺序整体重排。 */
    @PutMapping("/favorites/order")
    public List<ConversationResponse> reorderFavorites(@RequestBody FavoriteOrderRequest request) {
        Long userId = currentUser();
        repository.reorderFavorites(userId, request == null ? null : request.ids());
        return list();
    }

    /**
     * 删除会话内的一条对话（与其配对的那条一起删），并重建该会话的记忆，
     * 返回剩余消息让前端直接对齐，避免本地列表和后端不一致。
     */
    @DeleteMapping("/{id}/messages/{messageId}")
    public List<MessageResponse> deleteMessage(@PathVariable Long id, @PathVariable Long messageId) {
        Long userId = currentUser();
        repository.findConversation(id, userId)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "会话不存在"));
        try {
            return service.deleteMessagePair(userId, id, messageId).stream()
                    .map(MessageResponse::from)
                    .toList();
        }
        catch (IllegalArgumentException e) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, e.getMessage());
        }
    }

    /**
     * 已收藏的会话保持原排序号；重新收藏同一会话时不打乱它在收藏区的位置。
     */
    private Integer resolveFavoriteOrder(Long userId, ChatConversationDO conv) {
        if (conv.isFavorite() && conv.getFavoriteOrder() != null) {
            return conv.getFavoriteOrder();
        }
        return repository.maxFavoriteOrder(userId) + 1;
    }

    private static String normalizeNote(String note) {
        if (note == null) {
            return null;
        }
        String trimmed = note.trim();
        if (trimmed.isEmpty()) {
            return null;
        }
        return trimmed.length() <= 120 ? trimmed : trimmed.substring(0, 120);
    }

    private Long currentUser() {
        Long userId = UserContextHolder.currentUserId();
        if (userId == null) {
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "未登录");
        }
        return userId;
    }

    private static long toEpochMs(LocalDateTime time) {
        return time == null ? 0L : time.atZone(ZoneId.systemDefault()).toInstant().toEpochMilli();
    }
}

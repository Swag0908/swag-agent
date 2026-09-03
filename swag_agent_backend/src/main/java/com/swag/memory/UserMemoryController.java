package com.swag.memory;

import com.swag.auth.UserContextHolder;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

import java.time.LocalDateTime;
import java.time.ZoneId;
import java.util.List;

/**
 * 「我的记忆」管理 REST：查看、删除单条、开关（ChatGPT Memory 式管理面板）。
 */
@RestController
@RequestMapping("/chat/user-memory")
public class UserMemoryController {

    public record Item(Long id, String content, long createdAtMs) {
        static Item from(UserMemoryDO memory) {
            return new Item(memory.getId(), memory.getContent(),
                    toEpochMs(memory.getCreatedAt()));
        }
    }

    public record MemoryResponse(boolean enabled, List<Item> items) {
    }

    public record SettingsRequest(boolean enabled) {
    }

    private final UserMemoryService service;

    public UserMemoryController(UserMemoryService service) {
        this.service = service;
    }

    @GetMapping
    public MemoryResponse list() {
        Long userId = currentUser();
        List<Item> items = service.list(userId).stream().map(Item::from).toList();
        return new MemoryResponse(service.isEnabled(userId), items);
    }

    @PutMapping("/settings")
    public void updateSettings(@RequestBody SettingsRequest request) {
        service.setEnabled(currentUser(), request.enabled());
    }

    @DeleteMapping("/{id}")
    public void delete(@PathVariable Long id) {
        if (!service.delete(currentUser(), id)) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "记忆不存在");
        }
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

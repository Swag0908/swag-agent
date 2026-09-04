package com.swag.sites;

import com.swag.auth.UserContextHolder;
import org.springframework.http.CacheControl;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PatchMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

import java.util.Optional;

/**
 * 常用网站 REST 接口，供「常用网站」页使用。
 */
@RestController
@RequestMapping("/bookmarks")
public class WebsiteController {

    public record FolderRequest(String name, Long parentId) {
    }

    public record BookmarkRequest(
            String name,
            String url,
            String description,
            String iconUrl,
            Long folderId) {
    }

    private final WebsiteService service;
    private final WebsiteIconService iconService;

    public WebsiteController(WebsiteService service, WebsiteIconService iconService) {
        this.service = service;
        this.iconService = iconService;
    }

    @GetMapping
    public WebsiteViews.Library list(
            @RequestParam(required = false) Long folderId,
            @RequestParam(required = false) String q,
            @RequestParam(defaultValue = "false") boolean unclassified) {
        return service.library(currentUser(), folderId, q, unclassified);
    }

    @PostMapping("/folders")
    public WebsiteViews.FolderNode createFolder(@RequestBody FolderRequest request) {
        return service.createFolder(currentUser(), request.name(), request.parentId());
    }

    @PatchMapping("/folders/{id}")
    public WebsiteViews.FolderNode updateFolder(
            @PathVariable Long id,
            @RequestBody FolderRequest request) {
        return service.updateFolder(currentUser(), id, request.name(), request.parentId());
    }

    @DeleteMapping("/folders/{id}")
    public void deleteFolder(
            @PathVariable Long id,
            @RequestParam(defaultValue = "false") boolean cascade) {
        service.deleteFolder(currentUser(), id, cascade);
    }

    @PostMapping
    public WebsiteViews.BookmarkView create(@RequestBody BookmarkRequest request) {
        return service.createBookmark(
                currentUser(), request.name(), request.url(), request.description(),
                request.iconUrl(), request.folderId());
    }

    @PatchMapping("/{id}")
    public WebsiteViews.BookmarkView update(
            @PathVariable Long id,
            @RequestBody BookmarkRequest request) {
        return service.updateBookmark(
                currentUser(), id, request.name(), request.url(), request.description(),
                request.iconUrl(), request.folderId());
    }

    @GetMapping("/{id}/icon")
    public ResponseEntity<byte[]> icon(@PathVariable Long id) {
        Optional<WebsiteRepository.CachedIcon> icon = iconService.iconFor(currentUser(), id);
        if (icon.isEmpty()) {
            return ResponseEntity.notFound().build();
        }
        WebsiteRepository.CachedIcon value = icon.get();
        MediaType contentType;
        try {
            contentType = MediaType.parseMediaType(value.contentType());
        }
        catch (IllegalArgumentException ignored) {
            contentType = MediaType.APPLICATION_OCTET_STREAM;
        }
        return ResponseEntity.ok()
                .contentType(contentType)
                .cacheControl(CacheControl.noCache().cachePrivate())
                .body(value.data());
    }

    @DeleteMapping("/{id}")
    public void delete(@PathVariable Long id) {
        service.deleteBookmark(currentUser(), id);
    }

    private Long currentUser() {
        Long userId = UserContextHolder.currentUserId();
        if (userId == null) {
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "未登录");
        }
        return userId;
    }
}

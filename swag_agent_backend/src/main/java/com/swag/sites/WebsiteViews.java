package com.swag.sites;

import java.time.LocalDateTime;
import java.util.List;

/**
 * 常用网站模块的前端视图对象。
 */
public final class WebsiteViews {

    private WebsiteViews() {
    }

    public record FolderNode(
            Long id,
            String name,
            Long parentId,
            int sortOrder,
            int bookmarkCount,
            List<FolderNode> children) {
    }

    public record BookmarkView(
            Long id,
            Long folderId,
            String name,
            String url,
            String description,
            String iconUrl,
            int sortOrder,
            LocalDateTime createdAt,
            LocalDateTime updatedAt) {

        static BookmarkView from(WebsiteBookmarkDO bookmark) {
            return new BookmarkView(
                    bookmark.getId(),
                    bookmark.getFolderId(),
                    bookmark.getName(),
                    bookmark.getUrl(),
                    bookmark.getDescription(),
                    bookmark.getIconUrl(),
                    bookmark.getSortOrder(),
                    bookmark.getCreatedAt(),
                    bookmark.getUpdatedAt());
        }
    }

    public record Library(
            List<FolderNode> folders,
            List<BookmarkView> bookmarks,
            int total) {
    }
}

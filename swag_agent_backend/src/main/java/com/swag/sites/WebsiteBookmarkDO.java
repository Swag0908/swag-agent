package com.swag.sites;

import lombok.Data;

import java.time.LocalDateTime;

/**
 * 常用网站书签实体，folderId 为空表示未分类。
 */
@Data
public class WebsiteBookmarkDO {
    private Long id;
    private Long userId;
    private Long folderId;
    private String name;
    private String url;
    private String description;
    private String iconUrl;
    private int sortOrder;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;
}

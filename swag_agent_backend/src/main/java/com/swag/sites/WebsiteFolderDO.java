package com.swag.sites;

import lombok.Data;

import java.time.LocalDateTime;

/**
 * 常用网站文件夹实体，parentId 为空表示根目录。
 */
@Data
public class WebsiteFolderDO {
    private Long id;
    private Long userId;
    private String name;
    private Long parentId;
    private int sortOrder;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;
}

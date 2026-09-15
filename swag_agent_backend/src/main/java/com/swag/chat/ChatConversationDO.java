package com.swag.chat;

import lombok.Data;

import java.time.LocalDateTime;

/**
 * 历史会话实体（DeepSeek 式工作区里的一个会话）。
 */
@Data
public class ChatConversationDO {
    private Long id;
    private Long userId;
    /** 自动从首句用户消息生成；未生成前为空串。 */
    private String title;
    /** 是否被用户收藏（收藏的会话在侧边栏置顶）。 */
    private boolean favorite;
    /** 收藏备注名：只影响列表展示，不改写会话原标题。 */
    private String favoriteNote;
    /** 收藏区内的手动排序号（越小越靠前）；未收藏时为 null。 */
    private Integer favoriteOrder;
    /** 收藏时间，用于没有手动排序时的兜底排序。 */
    private LocalDateTime favoritedAt;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;
}

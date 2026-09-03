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
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;
}

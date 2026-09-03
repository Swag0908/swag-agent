package com.swag.memory;

import lombok.Data;

import java.time.LocalDateTime;

/**
 * 用户长期记忆（ChatGPT Memory 式）：
 * 跨会话、只存用户主动要求记住的精炼偏好/事实，与「会话内短期记忆」和
 * 「会话级 pgvector 语义记忆」相互独立。
 */
@Data
public class UserMemoryDO {
    private Long id;
    private Long userId;
    /** 一句精炼事实，例如「用户偏好用 Markdown 表格回复」。 */
    private String content;
    private LocalDateTime createdAt;
    private LocalDateTime updatedAt;
}

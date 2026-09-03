package com.swag.chat;

import lombok.Data;

import java.time.LocalDateTime;

/**
 * 会话内的一条消息（仅 user / assistant 的展示文本，
 * 与 Spring AI 记忆内部的存储相互独立）。
 */
@Data
public class ChatMessageDO {
    private Long id;
    private Long conversationId;
    private Long userId;
    /** user / assistant。 */
    private String role;
    private String content;
    private LocalDateTime createdAt;
}

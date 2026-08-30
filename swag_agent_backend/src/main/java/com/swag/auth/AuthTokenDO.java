package com.swag.auth;

import lombok.Data;

import java.time.LocalDateTime;

/**
 * 登录令牌实体。
 */
@Data
public class AuthTokenDO {
    private String token;
    private Long userId;
    private LocalDateTime expiresAt;
    private LocalDateTime createdAt;
}

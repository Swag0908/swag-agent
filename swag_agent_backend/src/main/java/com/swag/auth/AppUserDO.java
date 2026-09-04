package com.swag.auth;

import lombok.Data;

import java.time.LocalDateTime;

/**
 * 用户实体。
 */
@Data
public class AppUserDO {
    private Long id;
    private String username;
    private String passwordHash;
    private String displayName;
    /** 角色：ADMIN / USER。 */
    private String role;
    private LocalDateTime createdAt;
}

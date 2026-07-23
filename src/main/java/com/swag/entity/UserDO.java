package com.swag.entity;

import lombok.Data;

@Data
public class UserDO {
    private Long id;
    private Long userId;
    private String username;
    private String password;
    private String email;
}

package com.swag.auth;

import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.stereotype.Component;

/**
 * 启动时预置管理员账号（幂等，已存在则跳过）。
 */
@Component
public class AdminUserSeeder implements ApplicationRunner {

    private final AuthService authService;

    public AdminUserSeeder(AuthService authService) {
        this.authService = authService;
    }

    @Override
    public void run(ApplicationArguments args) {
        if (authService.findByUsername("swag").isEmpty()) {
            authService.register("swag", "cgynhsy12345", "管理员");
        }
    }
}

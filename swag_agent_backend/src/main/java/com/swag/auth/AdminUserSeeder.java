package com.swag.auth;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.stereotype.Component;

import java.util.Arrays;
import java.util.List;

/**
 * 启动时预置管理员账号（幂等，已存在则跳过），并确保其角色为 ADMIN。
 */
@Component
public class AdminUserSeeder implements ApplicationRunner {

    private final AuthService authService;
    private final List<String> adminUsernames;
    private final String adminPassword;

    public AdminUserSeeder(AuthService authService,
                           @Value("${app.auth.admin-usernames:swag}") String adminUsernames,
                           @Value("${app.auth.admin-password:cgynhsy12345}") String adminPassword) {
        this.authService = authService;
        this.adminUsernames = Arrays.stream(adminUsernames.split(","))
                .map(String::trim)
                .filter(name -> !name.isEmpty())
                .toList();
        this.adminPassword = adminPassword;
    }

    @Override
    public void run(ApplicationArguments args) {
        for (String admin : adminUsernames) {
            if (authService.findByUsername(admin).isEmpty()) {
                authService.registerBootstrap(admin, adminPassword, "管理员", "ADMIN");
            }
        }
    }
}

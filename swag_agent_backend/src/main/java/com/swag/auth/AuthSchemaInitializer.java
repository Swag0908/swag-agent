package com.swag.auth;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.jdbc.core.JdbcOperations;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Component;

import java.util.Arrays;
import java.util.List;

/**
 * 启动时的用户体系幂等初始化（在 AdminUserSeeder 之前执行）：
 * <ol>
 *   <li>给 {@code app_user} 补 {@code role} 列（老库升级，幂等：已有则跳过）；</li>
 *   <li>把配置的管理员用户名（默认 swag）在库中置为 ADMIN；</li>
 *   <li>确保注册设置行存在（无则自动生成初始注册码）。</li>
 * </ol>
 * 不做 Flyway 迁移：auth 相关表长期由启动初始化维护（与本项目其它表的做法一致）。
 */
@Component
@Order(Ordered.HIGHEST_PRECEDENCE)
public class AuthSchemaInitializer implements ApplicationRunner {

    private final NamedParameterJdbcTemplate jdbc;
    private final RegisterSettingsService registerSettingsService;
    private final List<String> adminUsernames;

    public AuthSchemaInitializer(
            NamedParameterJdbcTemplate jdbc,
            RegisterSettingsService registerSettingsService,
            @Value("${app.auth.admin-usernames:swag}") String adminUsernames) {
        this.jdbc = jdbc;
        this.registerSettingsService = registerSettingsService;
        this.adminUsernames = Arrays.stream(adminUsernames.split(","))
                .map(String::trim)
                .filter(name -> !name.isEmpty())
                .toList();
    }

    @Override
    public void run(ApplicationArguments args) {
        ensureRoleColumn();
        ensureAdminRoles();
        registerSettingsService.ensureInitialized();
    }

    private void ensureRoleColumn() {
        JdbcOperations plain = jdbc.getJdbcOperations();
        Integer count = plain.queryForObject("""
                        SELECT COUNT(*) FROM information_schema.COLUMNS
                        WHERE TABLE_SCHEMA = DATABASE()
                          AND TABLE_NAME = 'app_user'
                          AND COLUMN_NAME = 'role'
                        """,
                Integer.class);
        if (count == null || count == 0) {
            plain.execute("ALTER TABLE app_user ADD COLUMN role VARCHAR(16) NOT NULL DEFAULT 'USER'");
        }
    }

    private void ensureAdminRoles() {
        if (adminUsernames.isEmpty()) {
            return;
        }
        jdbc.update("UPDATE app_user SET role = 'ADMIN' WHERE username IN (:usernames)",
                new MapSqlParameterSource("usernames", adminUsernames));
    }
}

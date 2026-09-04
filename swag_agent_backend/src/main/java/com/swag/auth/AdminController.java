package com.swag.auth;

import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

import java.time.ZoneId;
import java.util.List;
import java.util.Locale;
import java.util.Set;

/**
 * 管理员端 REST（仅 ADMIN 角色可访问，其余一律 403）。
 * <p>
 * 覆盖：注册码查看/换新/自定义、新用户注册总开关、用户角色管理（提升/取消管理员）。
 */
@RestController
@RequestMapping("/auth/admin")
public class AdminController {

    public static final String ROLE_ADMIN = "ADMIN";
    public static final String ROLE_USER = "USER";
    private static final Set<String> ROLES = Set.of(ROLE_ADMIN, ROLE_USER);

    public record SettingsResponse(boolean registrationEnabled, String registerCode, Long updatedAtMs) {
    }

    public record UpdateSettingsRequest(Boolean registrationEnabled, String registerCode) {
    }

    public record RoleRequest(String role) {
    }

    public record UserView(Long id, String username, String displayName, String role, Long createdAtMs) {
    }

    private final AuthService authService;
    private final RegisterSettingsService registerSettingsService;

    public AdminController(AuthService authService, RegisterSettingsService registerSettingsService) {
        this.authService = authService;
        this.registerSettingsService = registerSettingsService;
    }

    @GetMapping("/register-settings")
    public SettingsResponse settings() {
        requireAdmin();
        return toResponse(registerSettingsService.current());
    }

    /** 更新注册开关和/或自定义注册码；null 字段表示保持原值。 */
    @PutMapping("/register-settings")
    public SettingsResponse updateSettings(@RequestBody UpdateSettingsRequest request) {
        AppUserDO admin = requireAdmin();
        RegisterSettingsService.Settings settings = registerSettingsService.update(
                request.registrationEnabled(), request.registerCode(), admin.getId());
        return toResponse(settings);
    }

    /** 一键换新注册码（旧码立即失效）。 */
    @PostMapping("/register-settings/regenerate")
    public SettingsResponse regenerate() {
        AppUserDO admin = requireAdmin();
        return toResponse(registerSettingsService.regenerate(admin.getId()));
    }

    @GetMapping("/users")
    public List<UserView> users() {
        requireAdmin();
        return authService.listUsers().stream()
                .map(u -> new UserView(u.getId(), u.getUsername(), u.getDisplayName(),
                        u.getRole() == null ? ROLE_USER : u.getRole(),
                        u.getCreatedAt() == null ? 0
                                : u.getCreatedAt().atZone(ZoneId.systemDefault()).toInstant().toEpochMilli()))
                .toList();
    }

    /** 提升/取消管理员（ADMIN / USER）。 */
    @PutMapping("/users/{id}/role")
    public UserView updateRole(@PathVariable Long id, @RequestBody RoleRequest request) {
        AppUserDO admin = requireAdmin();
        String role = request.role() == null ? "" : request.role().trim().toUpperCase(Locale.ROOT);
        if (!ROLES.contains(role)) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "角色只能是 ADMIN 或 USER");
        }
        if (admin.getId().equals(id)) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "不能修改自己的角色");
        }
        AppUserDO target = authService.findById(id)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "用户不存在"));
        if (ROLE_ADMIN.equals(target.getRole()) && ROLE_USER.equals(role) && authService.countAdmins() <= 1) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "至少保留一名管理员");
        }
        authService.updateRole(id, role);
        target.setRole(role);
        return new UserView(target.getId(), target.getUsername(), target.getDisplayName(), role,
                target.getCreatedAt() == null ? 0
                        : target.getCreatedAt().atZone(ZoneId.systemDefault()).toInstant().toEpochMilli());
    }

    private AppUserDO requireAdmin() {
        Long userId = UserContextHolder.currentUserId();
        AppUserDO user = userId == null ? null : authService.findById(userId).orElse(null);
        if (user == null || !ROLE_ADMIN.equals(user.getRole())) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, "仅管理员可执行该操作");
        }
        return user;
    }

    private static SettingsResponse toResponse(RegisterSettingsService.Settings settings) {
        return new SettingsResponse(settings.registrationEnabled(),
                settings.registerCode(), settings.updatedAtMs());
    }
}

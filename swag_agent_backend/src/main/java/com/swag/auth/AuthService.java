package com.swag.auth;

import org.springframework.dao.DuplicateKeyException;
import org.springframework.http.HttpStatus;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;

import java.time.Duration;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Optional;
import java.util.UUID;

/**
 * 注册、登录、令牌校验。
 */
@Service
public class AuthService {

    private static final Duration TOKEN_TTL = Duration.ofDays(7);

    private final AuthRepository repository;
    private final PasswordEncoder passwordEncoder;
    private final RegisterSettingsService registerSettingsService;

    public AuthService(AuthRepository repository,
                       PasswordEncoder passwordEncoder,
                       RegisterSettingsService registerSettingsService) {
        this.repository = repository;
        this.passwordEncoder = passwordEncoder;
        this.registerSettingsService = registerSettingsService;
    }

    /**
     * 公开注册：必须先通过注册闸门（总开关开启 + 注册码正确），新用户一律 USER。
     */
    public AppUserDO register(String username, String password, String displayName, String registerCode) {
        registerSettingsService.assertCanRegister(registerCode);
        return createUser(username, password, displayName, "USER");
    }

    /**
     * 启动种子/内部创建：绕过注册码闸门，由调用方显式指定角色。
     * 只允许系统初始化（如预置管理员）使用。
     */
    public AppUserDO registerBootstrap(String username, String password, String displayName, String role) {
        return createUser(username, password, displayName, role);
    }

    private AppUserDO createUser(String username, String password, String displayName, String role) {
        String name = normalize(username);
        if (name.length() < 3 || name.length() > 64) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "用户名长度需在 3-64 位之间");
        }
        if (password == null || password.length() < 6) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "密码长度至少 6 位");
        }

        AppUserDO user = new AppUserDO();
        user.setUsername(name);
        user.setPasswordHash(passwordEncoder.encode(password));
        user.setDisplayName(displayName == null || displayName.isBlank() ? name : displayName.trim());
        user.setRole(role);
        user.setCreatedAt(LocalDateTime.now());
        try {
            return repository.insert(user);
        }
        catch (DuplicateKeyException exception) {
            throw new ResponseStatusException(HttpStatus.CONFLICT, "用户名已存在");
        }
    }

    public AuthTokenDO login(String username, String password) {
        AppUserDO user = repository.findByUsername(normalize(username))
                .orElseThrow(() -> new ResponseStatusException(
                        HttpStatus.UNAUTHORIZED, "用户名或密码错误"));
        if (!passwordEncoder.matches(password, user.getPasswordHash())) {
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "用户名或密码错误");
        }

        AuthTokenDO token = new AuthTokenDO();
        token.setToken(UUID.randomUUID().toString());
        token.setUserId(user.getId());
        token.setCreatedAt(LocalDateTime.now());
        token.setExpiresAt(LocalDateTime.now().plus(TOKEN_TTL));
        repository.insertToken(token);
        return token;
    }

    public Optional<Long> resolveUserId(String token) {
        if (token == null || token.isBlank()) {
            return Optional.empty();
        }
        return repository.findByToken(token)
                .filter(t -> t.getExpiresAt().isAfter(LocalDateTime.now()))
                .map(AuthTokenDO::getUserId);
    }

    public void logout(String token) {
        if (token != null && !token.isBlank()) {
            repository.deleteToken(token);
        }
    }

    public Optional<AppUserDO> findById(Long id) {
        return repository.findById(id);
    }

    public Optional<AppUserDO> findByUsername(String username) {
        return repository.findByUsername(normalize(username));
    }

    public List<AppUserDO> listUsers() {
        return repository.findAllOrderByCreatedDesc();
    }

    public void updateRole(Long id, String role) {
        repository.updateRole(id, role);
    }

    public long countAdmins() {
        return repository.countAdmins();
    }

    private String normalize(String username) {
        return username == null ? "" : username.trim();
    }
}

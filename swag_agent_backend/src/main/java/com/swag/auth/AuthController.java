package com.swag.auth;

import jakarta.servlet.http.HttpServletResponse;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

/**
 * 注册、登录、登出、当前用户。
 */
@RestController
@RequestMapping("/auth")
public class AuthController {

    public record RegisterRequest(String username, String password, String displayName, String registerCode) {
    }

    public record LoginRequest(String username, String password) {
    }

    public record AuthResponse(String token, Long userId, String username,
                               String displayName, String role) {
    }

    private final AuthService authService;
    private final ZipkinAccessCookie zipkinAccessCookie;

    public AuthController(AuthService authService, ZipkinAccessCookie zipkinAccessCookie) {
        this.authService = authService;
        this.zipkinAccessCookie = zipkinAccessCookie;
    }

    /** 公开注册：必须携带管理员提供的注册码，否则被注册闸门拒绝。 */
    @PostMapping("/register")
    public AuthResponse register(@RequestBody RegisterRequest request, HttpServletResponse response) {
        AppUserDO user = authService.register(
                request.username(), request.password(), request.displayName(), request.registerCode());
        AuthTokenDO token = authService.login(request.username(), request.password());
        zipkinAccessCookie.issue(response, token.getToken());
        return new AuthResponse(token.getToken(), user.getId(),
                user.getUsername(), user.getDisplayName(), user.getRole());
    }

    @PostMapping("/login")
    public AuthResponse login(@RequestBody LoginRequest request, HttpServletResponse response) {
        AuthTokenDO token = authService.login(request.username(), request.password());
        AppUserDO user = authService.findById(token.getUserId())
                .orElseThrow(() -> new ResponseStatusException(
                        HttpStatus.UNAUTHORIZED, "用户不存在"));
        zipkinAccessCookie.issue(response, token.getToken());
        return new AuthResponse(token.getToken(), user.getId(),
                user.getUsername(), user.getDisplayName(), user.getRole());
    }

    @PostMapping("/logout")
    public void logout(@RequestHeader(value = "Authorization", required = false) String authorization,
                       HttpServletResponse response) {
        authService.logout(bearerToken(authorization));
        zipkinAccessCookie.clear(response);
    }

    /**
     * 当前登录用户信息（前端启动时刷新本地缓存的显示名/角色，如旧会话升级为管理员后无需重新登录）。
     * 顺带补发 Zipkin 访问票据：功能上线前登录的老会话也能直接查看调用链。
     */
    @GetMapping("/me")
    public AuthResponse me(@RequestHeader(value = "Authorization", required = false) String authorization,
                           HttpServletResponse response) {
        Long userId = UserContextHolder.currentUserId();
        AppUserDO user = userId == null ? null : authService.findById(userId).orElse(null);
        if (user == null) {
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "请先登录");
        }
        zipkinAccessCookie.issue(response, bearerToken(authorization));
        return new AuthResponse(null, user.getId(),
                user.getUsername(), user.getDisplayName(), user.getRole());
    }

    private String bearerToken(String authorization) {
        if (authorization == null || !authorization.startsWith("Bearer ")) {
            return "";
        }
        return authorization.substring("Bearer ".length()).trim();
    }
}

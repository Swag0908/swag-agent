package com.swag.auth;

import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

/**
 * 注册、登录、登出。
 */
@RestController
@RequestMapping("/auth")
public class AuthController {

    public record RegisterRequest(String username, String password, String displayName) {
    }

    public record LoginRequest(String username, String password) {
    }

    public record AuthResponse(String token, Long userId, String username, String displayName) {
    }

    private final AuthService authService;

    public AuthController(AuthService authService) {
        this.authService = authService;
    }

    @PostMapping("/register")
    public AuthResponse register(@RequestBody RegisterRequest request) {
        AppUserDO user = authService.register(
                request.username(), request.password(), request.displayName());
        AuthTokenDO token = authService.login(request.username(), request.password());
        return new AuthResponse(token.getToken(), user.getId(),
                user.getUsername(), user.getDisplayName());
    }

    @PostMapping("/login")
    public AuthResponse login(@RequestBody LoginRequest request) {
        AuthTokenDO token = authService.login(request.username(), request.password());
        AppUserDO user = authService.findById(token.getUserId())
                .orElseThrow(() -> new ResponseStatusException(
                        HttpStatus.UNAUTHORIZED, "用户不存在"));
        return new AuthResponse(token.getToken(), user.getId(),
                user.getUsername(), user.getDisplayName());
    }

    @PostMapping("/logout")
    public void logout(@RequestHeader(value = "Authorization", required = false) String authorization) {
        authService.logout(bearerToken(authorization));
    }

    private String bearerToken(String authorization) {
        if (authorization == null || !authorization.startsWith("Bearer ")) {
            return "";
        }
        return authorization.substring("Bearer ".length()).trim();
    }
}

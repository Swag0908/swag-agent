package com.swag.auth;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletRequestWrapper;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;
import java.nio.charset.StandardCharsets;

/**
 * 登录鉴权入口，运行在 {@code AuditContextFilter} 之前，
 * 将解析出的用户 ID 覆盖到 {@code X-User-Id} 头，使审计链路自动带上真实用户。
 */
@Component
@Order(Ordered.HIGHEST_PRECEDENCE + 1)
public class AuthFilter extends OncePerRequestFilter {

    public static final String USER_ID_HEADER = "X-User-Id";

    private final AuthService authService;

    public AuthFilter(AuthService authService) {
        this.authService = authService;
    }

    @Override
    protected void doFilterInternal(
            HttpServletRequest request,
            HttpServletResponse response,
            FilterChain filterChain) throws ServletException, IOException {

        Long userId = authService.resolveUserId(bearerToken(request.getHeader("Authorization")))
                .orElse(null);

        boolean publicPath = isPublicPath(request.getRequestURI());
        if (!publicPath && userId == null) {
            response.setStatus(HttpStatus.UNAUTHORIZED.value());
            response.setContentType("application/json;charset=UTF-8");
            response.getOutputStream().write(
                    "{\"code\":\"UNAUTHORIZED\",\"message\":\"请先登录\"}"
                            .getBytes(StandardCharsets.UTF_8));
            return;
        }

        HttpServletRequest wrapped = new HttpServletRequestWrapper(request) {
            @Override
            public String getHeader(String name) {
                if (USER_ID_HEADER.equalsIgnoreCase(name) && userId != null) {
                    return userId.toString();
                }
                return super.getHeader(name);
            }
        };

        UserContextHolder.set(userId);
        try {
            filterChain.doFilter(wrapped, response);
        }
        finally {
            UserContextHolder.clear();
        }
    }

    private boolean isPublicPath(String path) {
        return path.startsWith("/auth/register")
                || path.startsWith("/auth/login")
                || path.startsWith("/actuator/")
                || path.equals("/error");
    }

    private String bearerToken(String authorization) {
        if (authorization == null || !authorization.startsWith("Bearer ")) {
            return null;
        }
        return authorization.substring("Bearer ".length()).trim();
    }
}

package com.swag.auth;

import jakarta.servlet.http.Cookie;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpHeaders;
import org.springframework.http.ResponseCookie;
import org.springframework.stereotype.Component;

import java.time.Duration;

/**
 * Zipkin 调用链 UI 的访问票据 Cookie。
 *
 * <p>Zipkin 本体没有登录能力，官方做法是前置反向代理做认证。这里由 nginx 的
 * {@code auth_request} 子请求回调 {@code /auth/zipkin-access} 放行，而子请求无法携带
 * {@code Authorization} 头（管理员通常是在新标签页里打开调用链链接），因此登录成功后
 * 额外下发一个 HttpOnly Cookie：作用域限定在 {@code /zipkin} 路径，且只有该鉴权接口读取，
 * 不会扩大其它接口的 CSRF 面。
 */
@Component
public class ZipkinAccessCookie {

    public static final String DEFAULT_NAME = "swag_zipkin_token";
    public static final String DEFAULT_PATH = "/zipkin";

    private final String name;
    private final String path;
    private final boolean secure;
    private final Duration ttl;

    public ZipkinAccessCookie(
            @Value("${app.zipkin-access.cookie-name:swag_zipkin_token}") String name,
            @Value("${app.zipkin-access.cookie-path:/zipkin}") String path,
            @Value("${app.zipkin-access.cookie-secure:false}") boolean secure,
            @Value("${app.zipkin-access.token-ttl:7d}") Duration ttl) {
        this.name = name;
        this.path = path;
        this.secure = secure;
        this.ttl = ttl;
    }

    public String getName() {
        return name;
    }

    public String getPath() {
        return path;
    }

    /** 登录成功时下发；token 为空则什么都不做。 */
    public void issue(HttpServletResponse response, String token) {
        if (token == null || token.isBlank()) {
            return;
        }
        response.addHeader(HttpHeaders.SET_COOKIE, build(token, ttl).toString());
    }

    /** 登出时立即失效。 */
    public void clear(HttpServletResponse response) {
        response.addHeader(HttpHeaders.SET_COOKIE, build("", Duration.ZERO).toString());
    }

    /** 从请求里取出票据；没有则返回 null。 */
    public String read(HttpServletRequest request) {
        Cookie[] cookies = request.getCookies();
        if (cookies == null) {
            return null;
        }
        for (Cookie cookie : cookies) {
            if (name.equals(cookie.getName())) {
                return cookie.getValue();
            }
        }
        return null;
    }

    private ResponseCookie build(String value, Duration maxAge) {
        return ResponseCookie.from(name, value)
                .httpOnly(true)
                .path(path)
                .sameSite("Lax")
                .secure(secure)
                .maxAge(maxAge)
                .build();
    }
}

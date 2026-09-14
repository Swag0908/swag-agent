package com.swag.auth;

import jakarta.servlet.http.HttpServletRequest;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RestController;

/**
 * Zipkin UI 的 nginx {@code auth_request} 鉴权入口：管理员登录态才放行。
 *
 * <p>只认 {@link ZipkinAccessCookie}（HttpOnly Cookie），因为 zipkin 页面是浏览器原生跳转，
 * 带不了 {@code Authorization} 头。返回：204 放行 / 401 未登录 / 403 非管理员。
 * 该接口在 {@link AuthFilter} 中属于公开路径，权限判断全部在这里完成，响应体不含敏感信息。
 */
@RestController
public class ZipkinAccessController {

    private final AuthService authService;
    private final ZipkinAccessCookie zipkinAccessCookie;

    public ZipkinAccessController(AuthService authService, ZipkinAccessCookie zipkinAccessCookie) {
        this.authService = authService;
        this.zipkinAccessCookie = zipkinAccessCookie;
    }

    @GetMapping("/auth/zipkin-access")
    public ResponseEntity<String> verify(HttpServletRequest request) {
        Long userId = authService.resolveUserId(zipkinAccessCookie.read(request)).orElse(null);
        AppUserDO user = userId == null ? null : authService.findById(userId).orElse(null);
        if (user == null) {
            return ResponseEntity.status(HttpStatus.UNAUTHORIZED).body("请先登录");
        }
        if (!AdminController.ROLE_ADMIN.equals(user.getRole())) {
            return ResponseEntity.status(HttpStatus.FORBIDDEN).body("仅管理员可查看调用链");
        }
        return ResponseEntity.noContent().build();
    }
}

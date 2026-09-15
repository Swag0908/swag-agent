package com.swag.audit.web;

import com.swag.audit.query.AuditChainQueryService;
import com.swag.audit.query.AuditChainView;
import com.swag.auth.AppUserDO;
import com.swag.auth.AuthService;
import com.swag.auth.UserContextHolder;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

import java.util.List;

/**
 * 管理端调用链列表（仅 ADMIN）。
 *
 * <p>与 {@code GET /audit/events/{auditId}} 的关系：那个接口按 auditId 看一条链的明细，
 * 这个接口列出最近的链本身，前端点一下就能拿 {@code zipkinTraceUrl} 跳 Zipkin。
 * 两者都要求登录，这里额外要求 ADMIN。
 */
@RestController
@RequestMapping("/audit/chains")
public class AuditChainController {

    public static final String ROLE_ADMIN = "ADMIN";

    private final AuditChainQueryService auditChainQueryService;
    private final AuthService authService;

    public AuditChainController(AuditChainQueryService auditChainQueryService,
                                AuthService authService) {
        this.auditChainQueryService = auditChainQueryService;
        this.authService = authService;
    }

    @GetMapping
    public List<AuditChainView> recent(
            @RequestParam(name = "limit", defaultValue = "30") int limit) {
        requireAdmin();
        return auditChainQueryService.recentChains(limit);
    }

    private void requireAdmin() {
        Long userId = UserContextHolder.currentUserId();
        AppUserDO user = userId == null ? null : authService.findById(userId).orElse(null);
        if (user == null || !ROLE_ADMIN.equals(user.getRole())) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, "仅管理员可查看调用链");
        }
    }
}

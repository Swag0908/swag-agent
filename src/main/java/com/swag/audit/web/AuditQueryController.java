package com.swag.audit.web;

import com.swag.audit.query.JdbcAuditQueryRepository;
import com.swag.audit.query.ZipkinTraceLinkBuilder;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;
import java.util.UUID;

/**
 * 审计事件查询 API。
 */
@RestController
@RequestMapping("/audit/events")
public class AuditQueryController {

    private final JdbcAuditQueryRepository repository;
    private final ZipkinTraceLinkBuilder zipkinTraceLinkBuilder;

    public AuditQueryController(
            JdbcAuditQueryRepository repository,
            ZipkinTraceLinkBuilder zipkinTraceLinkBuilder) {
        this.repository = repository;
        this.zipkinTraceLinkBuilder = zipkinTraceLinkBuilder;
    }

    @GetMapping("/{auditId}")
    public List<AuditEventResponse> findByAuditId(
            @PathVariable UUID auditId) {
        return repository.findByAuditId(auditId).stream()
                .map(event -> new AuditEventResponse(
                        event,
                        zipkinTraceLinkBuilder.build(event.traceId())))
                .toList();
    }
}

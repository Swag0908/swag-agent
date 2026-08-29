package com.swag.audit.web;

import com.swag.audit.confirmation.ConfirmationService;
import com.swag.audit.context.AuditContextHolder;
import com.swag.audit.context.AuditRequestContext;
import com.swag.audit.core.AuditEventCommand;
import com.swag.audit.core.AuditEventType;
import com.swag.audit.core.AuditRecorder;
import io.micrometer.tracing.BaggageInScope;
import io.micrometer.tracing.Span;
import io.micrometer.tracing.Tracer;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import java.io.IOException;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.UUID;

/**
 * HTTP 请求审计入口。
 * <p>
 * 运行在 Spring HTTP Observation Filter 之后，使当前 HTTP Span 已经可用。
 */
@Component
@Order(Ordered.HIGHEST_PRECEDENCE + 2)
public class AuditContextFilter extends OncePerRequestFilter {

    public static final String AUDIT_ID_HEADER = "X-Audit-Id";
    public static final String CONFIRMATION_ID_HEADER = "X-Confirmation-Id";
    public static final String REQUEST_ID_HEADER = "X-Request-Id";
    public static final String USER_ID_HEADER = "X-User-Id";
    public static final String TENANT_ID_HEADER = "X-Tenant-Id";

    private final Tracer tracer;
    private final AuditRecorder auditRecorder;
    private final ConfirmationService confirmationService;

    public AuditContextFilter(
            Tracer tracer,
            AuditRecorder auditRecorder,
            ConfirmationService confirmationService) {
        this.tracer = tracer;
        this.auditRecorder = auditRecorder;
        this.confirmationService = confirmationService;
    }

    @Override
    protected void doFilterInternal(
            HttpServletRequest request,
            HttpServletResponse response,
            FilterChain filterChain) throws ServletException, IOException {
        String actorId = headerOrDefault(request, USER_ID_HEADER, "anonymous");
        String tenantId = headerOrDefault(request, TENANT_ID_HEADER, "default");
        UUID confirmationId = parseUuid(request.getHeader(CONFIRMATION_ID_HEADER));
        UUID auditId = resolveAuditId(confirmationId, tenantId, actorId);
        String requestId = headerOrDefault(
                request,
                REQUEST_ID_HEADER,
                UUID.randomUUID().toString());
        String sessionId = request.getSession(false) == null
                ? null
                : request.getSession(false).getId();

        AuditRequestContext context = new AuditRequestContext(
                auditId,
                requestId,
                tenantId,
                actorId,
                sessionId,
                confirmationId);

        response.setHeader(AUDIT_ID_HEADER, auditId.toString());

        try (AuditContextHolder.Scope ignored = AuditContextHolder.open(context);
                BaggageInScope baggage = tracer.createBaggageInScope(
                        "audit_id",
                        auditId.toString())) {
            // span标记上auditId
            tagCurrentSpan(auditId);
            // 请求入库
            recordRequestReceived(request);

            try {
                filterChain.doFilter(request, response);
                recordRequestCompleted(request, response);
            }
            catch (Exception exception) {
                recordRequestFailed(request, exception);
                throw exception;
            }
        }
    }

    private UUID resolveAuditId(
            UUID confirmationId,
            String tenantId,
            String actorId) {
        if (confirmationId == null) {
            return UUID.randomUUID();
        }
        return confirmationService.resolveAuditIdForRetry(
                        confirmationId,
                        tenantId,
                        actorId)
                .orElseGet(UUID::randomUUID);
    }

    private void recordRequestReceived(HttpServletRequest request) {
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("method", request.getMethod());
        data.put("path", request.getRequestURI());
        data.put("remoteAddress", request.getRemoteAddr());
        data.put("userAgent", request.getHeader("User-Agent"));

        auditRecorder.record(AuditEventCommand.builder()
                .eventType(AuditEventType.REQUEST_RECEIVED)
                .executionStatus("RECEIVED")
                .actorType("USER")
                .eventData(data)
                .build());
    }

    private void recordRequestCompleted(
            HttpServletRequest request,
            HttpServletResponse response) {
        int status = response.getStatus();
        String executionStatus;
        if (status == HttpServletResponse.SC_CONFLICT) {
            executionStatus = "WAITING_CONFIRMATION";
        }
        else if (status >= 500) {
            executionStatus = "FAILED";
        }
        else if (status >= 400) {
            executionStatus = "REJECTED";
        }
        else {
            executionStatus = "SUCCEEDED";
        }

        auditRecorder.record(AuditEventCommand.builder()
                .eventType(status >= 500
                        ? AuditEventType.REQUEST_FAILED
                        : AuditEventType.REQUEST_COMPLETED)
                .executionStatus(executionStatus)
                .actorType("SYSTEM")
                .eventData(Map.of(
                        "method", request.getMethod(),
                        "path", request.getRequestURI(),
                        "httpStatus", status))
                .build());
    }

    private void recordRequestFailed(
            HttpServletRequest request,
            Exception exception) {
        auditRecorder.record(AuditEventCommand.builder()
                .eventType(AuditEventType.REQUEST_FAILED)
                .executionStatus("FAILED")
                .actorType("SYSTEM")
                .errorCode(exception.getClass().getSimpleName())
                .errorMessage(exception.getMessage())
                .eventData(Map.of(
                        "method", request.getMethod(),
                        "path", request.getRequestURI()))
                .build());
    }

    private void tagCurrentSpan(UUID auditId) {
        Span span = tracer.currentSpan();
        if (span != null) {
            span.tag("audit_id", auditId.toString());
        }
    }

    private UUID parseUuid(String value) {
        if (value == null || value.isBlank()) {
            return null;
        }
        try {
            return UUID.fromString(value);
        }
        catch (IllegalArgumentException ignored) {
            return null;
        }
    }

    private String headerOrDefault(
            HttpServletRequest request,
            String headerName,
            String defaultValue) {
        String value = request.getHeader(headerName);
        return value == null || value.isBlank() ? defaultValue : value;
    }
}

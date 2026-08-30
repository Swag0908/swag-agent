package com.swag.audit.query;

import java.time.Instant;
import java.util.UUID;

/**
 * 审计页面使用的事件只读视图。
 */
public record AuditEventView(
        UUID eventId,
        UUID auditId,
        String requestId,
        String traceId,
        String spanId,
        String parentSpanId,
        String tenantId,
        String actorType,
        String actorId,
        String eventType,
        String executionStatus,
        String agentName,
        String modelName,
        String toolName,
        String toolCallId,
        UUID confirmationId,
        String actionDigest,
        String inputDigest,
        String outputDigest,
        String eventData,
        String errorCode,
        String errorMessage,
        Instant occurredAt,
        Instant recordedAt) {
}

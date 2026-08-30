package com.swag.audit.core;

import lombok.Builder;

import java.util.Map;
import java.util.UUID;

/**
 * 写入审计事件所需的业务数据。
 * <p>
 * audit_id、trace_id、actor 等公共上下文由 AuditRecorder 自动补充。
 */
@Builder
public record AuditEventCommand(
        AuditEventType eventType,
        String executionStatus,
        UUID auditIdOverride,
        UUID parentEventId,
        String actorType,
        String actorIdOverride,
        String agentName,
        String agentVersion,
        String modelName,
        String toolName,
        String toolCallId,
        UUID confirmationId,
        String actionDigest,
        String inputRef,
        String inputDigest,
        String outputRef,
        String outputDigest,
        Map<String, ?> eventData,
        String errorCode,
        String errorMessage) {
}

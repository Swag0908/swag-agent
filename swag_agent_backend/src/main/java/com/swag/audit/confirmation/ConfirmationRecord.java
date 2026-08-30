package com.swag.audit.confirmation;

import java.time.Instant;
import java.util.UUID;

/**
 * 工具确认的持久化记录。
 */
public record ConfirmationRecord(
        UUID confirmationId,
        UUID auditId,
        String toolCallId,
        String tenantId,
        String actorId,
        String toolName,
        String canonicalInput,
        String actionDigest,
        ConfirmationStatus status,
        String decisionReason,
        Instant requestedAt,
        Instant decidedAt,
        Instant expiresAt,
        Instant consumedAt) {
}

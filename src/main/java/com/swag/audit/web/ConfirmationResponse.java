package com.swag.audit.web;

import com.swag.audit.confirmation.ConfirmationRecord;

import java.time.Instant;
import java.util.UUID;

/**
 * 工具确认状态响应。
 */
public record ConfirmationResponse(
        UUID confirmationId,
        UUID auditId,
        String toolName,
        String status,
        Instant requestedAt,
        Instant decidedAt,
        Instant expiresAt,
        Instant consumedAt) {

    public static ConfirmationResponse from(ConfirmationRecord record) {
        return new ConfirmationResponse(
                record.confirmationId(),
                record.auditId(),
                record.toolName(),
                record.status().name(),
                record.requestedAt(),
                record.decidedAt(),
                record.expiresAt(),
                record.consumedAt());
    }
}

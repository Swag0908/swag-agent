package com.swag.audit.confirmation;

import java.util.UUID;

/**
 * 工具调用需要用户确认时中断当前 Agent 调用。
 */
public class ConfirmationRequiredException extends RuntimeException {

    private final UUID confirmationId;
    private final UUID auditId;
    private final String toolName;
    private final InstantWindow validity;

    public ConfirmationRequiredException(
            UUID confirmationId,
            UUID auditId,
            String toolName,
            InstantWindow validity) {
        super("Tool call requires user confirmation: " + toolName);
        this.confirmationId = confirmationId;
        this.auditId = auditId;
        this.toolName = toolName;
        this.validity = validity;
    }

    public UUID getConfirmationId() {
        return confirmationId;
    }

    public UUID getAuditId() {
        return auditId;
    }

    public String getToolName() {
        return toolName;
    }

    public InstantWindow getValidity() {
        return validity;
    }

    /**
     * 确认请求的开始和过期时间。
     */
    public record InstantWindow(java.time.Instant requestedAt, java.time.Instant expiresAt) {
    }
}

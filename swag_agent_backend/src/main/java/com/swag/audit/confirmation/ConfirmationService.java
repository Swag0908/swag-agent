package com.swag.audit.confirmation;

import com.swag.audit.config.AuditProperties;
import com.swag.audit.context.AuditContextHolder;
import com.swag.audit.context.AuditRequestContext;
import com.swag.audit.core.AuditEventCommand;
import com.swag.audit.core.AuditEventType;
import com.swag.audit.core.AuditRecorder;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import java.time.Instant;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;

/**
 * 管理高风险工具的确认状态机。
 */
@Service
public class ConfirmationService {

    private final JdbcConfirmationRepository repository;
    private final AuditRecorder auditRecorder;
    private final AuditProperties properties;

    public ConfirmationService(
            JdbcConfirmationRepository repository,
            AuditRecorder auditRecorder,
            AuditProperties properties) {
        this.repository = repository;
        this.auditRecorder = auditRecorder;
        this.properties = properties;
    }

    public boolean requiresConfirmation(String toolName) {
        return properties.getConfirmationRequiredTools().contains(toolName);
    }

    /**
     * 创建待确认动作并中断本次工具执行。
     */
    @Transactional
    public ConfirmationRequiredException requestConfirmation(
            String toolName,
            String toolCallId,
            String canonicalInput,
            String actionDigest) {
        AuditRequestContext context = requireContext();
        Instant requestedAt = Instant.now();
        Instant expiresAt = requestedAt.plus(properties.getConfirmationTtl());
        UUID confirmationId = UUID.randomUUID();

        ConfirmationRecord confirmation = new ConfirmationRecord(
                confirmationId,
                context.auditId(),
                toolCallId,
                context.tenantId(),
                context.actorId(),
                toolName,
                canonicalInput,
                actionDigest,
                ConfirmationStatus.PENDING,
                null,
                requestedAt,
                null,
                expiresAt,
                null);

        repository.insert(confirmation);
        auditRecorder.record(AuditEventCommand.builder()
                .eventType(AuditEventType.CONFIRMATION_REQUESTED)
                .executionStatus(ConfirmationStatus.PENDING.name())
                .actorType("AGENT")
                .toolName(toolName)
                .toolCallId(toolCallId)
                .confirmationId(confirmationId)
                .actionDigest(actionDigest)
                .eventData(Map.of("expiresAt", expiresAt.toString()))
                .build());

        return new ConfirmationRequiredException(
                confirmationId,
                context.auditId(),
                toolName,
                new ConfirmationRequiredException.InstantWindow(requestedAt, expiresAt));
    }

    /**
     * 批准或拒绝一项待确认动作。
     */
    @Transactional(noRollbackFor = ConfirmationValidationException.class)
    public ConfirmationRecord decide(
            UUID confirmationId,
            ConfirmationStatus decision,
            String reason) {
        if (decision != ConfirmationStatus.APPROVED && decision != ConfirmationStatus.DENIED) {
            throw new ConfirmationValidationException("Decision must be APPROVED or DENIED");
        }

        AuditRequestContext context = requireContext();
        ConfirmationRecord current = repository.findByIdForUpdate(confirmationId)
                .orElseThrow(() -> new ConfirmationValidationException("Confirmation not found"));

        verifyActor(current, context);
        expireIfNecessary(current);

        if (current.status() != ConfirmationStatus.PENDING) {
            throw new ConfirmationValidationException(
                    "Confirmation is not pending: " + current.status());
        }

        Instant decidedAt = Instant.now();
        if (repository.decide(confirmationId, decision, reason, decidedAt) != 1) {
            throw new ConfirmationValidationException("Confirmation state changed concurrently");
        }

        auditRecorder.record(AuditEventCommand.builder()
                .eventType(decision == ConfirmationStatus.APPROVED
                        ? AuditEventType.CONFIRMATION_APPROVED
                        : AuditEventType.CONFIRMATION_DENIED)
                .executionStatus(decision.name())
                .auditIdOverride(current.auditId())
                .actorType("USER")
                .actorIdOverride(context.actorId())
                .toolName(current.toolName())
                .toolCallId(current.toolCallId())
                .confirmationId(confirmationId)
                .actionDigest(current.actionDigest())
                .eventData(reason == null || reason.isBlank()
                        ? Map.of()
                        : Map.of("reason", reason))
                .build());

        return repository.findById(confirmationId).orElseThrow();
    }

    /**
     * 执行工具前验证并以原子方式消费一次已批准确认。
     */
    @Transactional(noRollbackFor = ConfirmationValidationException.class)
    public void consumeApproval(
            UUID confirmationId,
            String toolName,
            String actionDigest) {
        AuditRequestContext context = requireContext();
        ConfirmationRecord current = repository.findByIdForUpdate(confirmationId)
                .orElseThrow(() -> new ConfirmationValidationException("Confirmation not found"));

        verifyActor(current, context);
        expireIfNecessary(current);

        if (current.status() != ConfirmationStatus.APPROVED) {
            throw new ConfirmationValidationException(
                    "Confirmation is not approved: " + current.status());
        }
        if (!current.toolName().equals(toolName)
                || !current.actionDigest().equals(actionDigest)) {
            throw new ConfirmationValidationException(
                    "Confirmed action does not match the requested tool call");
        }

        Instant consumedAt = Instant.now();
        if (repository.consume(confirmationId, consumedAt) != 1) {
            throw new ConfirmationValidationException("Confirmation has already been consumed");
        }

        auditRecorder.record(AuditEventCommand.builder()
                .eventType(AuditEventType.CONFIRMATION_CONSUMED)
                .executionStatus(ConfirmationStatus.CONSUMED.name())
                .auditIdOverride(current.auditId())
                .actorType("SYSTEM")
                .toolName(toolName)
                .toolCallId(current.toolCallId())
                .confirmationId(confirmationId)
                .actionDigest(actionDigest)
                .build());
    }

    /**
     * 重试请求携带确认 ID 时，恢复最初的 audit_id，保持同一条审计链。
     */
    public Optional<UUID> resolveAuditIdForRetry(
            UUID confirmationId,
            String tenantId,
            String actorId) {
        return repository.findById(confirmationId)
                .filter(record -> record.status() == ConfirmationStatus.APPROVED)
                .filter(record -> record.expiresAt().isAfter(Instant.now()))
                .filter(record -> equalsNullable(record.tenantId(), tenantId))
                .filter(record -> equalsNullable(record.actorId(), actorId))
                .map(ConfirmationRecord::auditId);
    }

    public Optional<ConfirmationRecord> find(UUID confirmationId) {
        return repository.findById(confirmationId);
    }

    private void expireIfNecessary(ConfirmationRecord current) {
        if (current.expiresAt().isAfter(Instant.now())) {
            return;
        }

        if (repository.markExpired(current.confirmationId(), Instant.now()) == 1) {
            auditRecorder.record(AuditEventCommand.builder()
                    .eventType(AuditEventType.CONFIRMATION_EXPIRED)
                    .executionStatus(ConfirmationStatus.EXPIRED.name())
                    .auditIdOverride(current.auditId())
                    .actorType("SYSTEM")
                    .toolName(current.toolName())
                    .toolCallId(current.toolCallId())
                    .confirmationId(current.confirmationId())
                    .actionDigest(current.actionDigest())
                    .build());
        }
        throw new ConfirmationValidationException("Confirmation has expired");
    }

    private void verifyActor(
            ConfirmationRecord confirmation,
            AuditRequestContext context) {
        if (!equalsNullable(confirmation.tenantId(), context.tenantId())
                || !equalsNullable(confirmation.actorId(), context.actorId())) {
            throw new ConfirmationValidationException(
                    "Confirmation does not belong to the current user");
        }
    }

    private boolean equalsNullable(String left, String right) {
        return left == null ? right == null : left.equals(right);
    }

    private AuditRequestContext requireContext() {
        return AuditContextHolder.current()
                .orElseThrow(() -> new IllegalStateException("No audit context is active"));
    }
}

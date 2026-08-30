package com.swag.audit.confirmation;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.List;
import java.util.Optional;
import java.util.UUID;

/**
 * 工具确认状态的 JDBC 存储。
 */
@Repository
public class JdbcConfirmationRepository {

    private static final String SELECT_COLUMNS = """
            confirmation_id, audit_id, tool_call_id, tenant_id, actor_id,
            tool_name, canonical_input, action_digest, status, decision_reason,
            requested_at, decided_at, expires_at, consumed_at
            """;

    private final JdbcTemplate jdbcTemplate;

    public JdbcConfirmationRepository(JdbcTemplate jdbcTemplate) {
        this.jdbcTemplate = jdbcTemplate;
    }

    public void insert(ConfirmationRecord record) {
        jdbcTemplate.update("""
                        INSERT INTO audit_confirmation (
                            confirmation_id, audit_id, tool_call_id, tenant_id, actor_id,
                            tool_name, canonical_input, action_digest, status,
                            requested_at, expires_at
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                record.confirmationId().toString(),
                record.auditId().toString(),
                record.toolCallId(),
                record.tenantId(),
                record.actorId(),
                record.toolName(),
                record.canonicalInput(),
                record.actionDigest(),
                record.status().name(),
                Timestamp.from(record.requestedAt()),
                Timestamp.from(record.expiresAt()));
    }

    public Optional<ConfirmationRecord> findById(UUID confirmationId) {
        return queryOne("""
                SELECT %s
                FROM audit_confirmation
                WHERE confirmation_id = ?
                """.formatted(SELECT_COLUMNS), confirmationId);
    }

    public Optional<ConfirmationRecord> findByIdForUpdate(UUID confirmationId) {
        return queryOne("""
                SELECT %s
                FROM audit_confirmation
                WHERE confirmation_id = ?
                FOR UPDATE
                """.formatted(SELECT_COLUMNS), confirmationId);
    }

    public int decide(
            UUID confirmationId,
            ConfirmationStatus status,
            String reason,
            Instant decidedAt) {
        return jdbcTemplate.update("""
                        UPDATE audit_confirmation
                        SET status = ?, decision_reason = ?, decided_at = ?
                        WHERE confirmation_id = ? AND status = 'PENDING'
                        """,
                status.name(),
                reason,
                Timestamp.from(decidedAt),
                confirmationId.toString());
    }

    public int markExpired(UUID confirmationId, Instant expiredAt) {
        return jdbcTemplate.update("""
                        UPDATE audit_confirmation
                        SET status = 'EXPIRED', decided_at = ?
                        WHERE confirmation_id = ? AND status IN ('PENDING', 'APPROVED')
                        """,
                Timestamp.from(expiredAt),
                confirmationId.toString());
    }

    public int consume(UUID confirmationId, Instant consumedAt) {
        return jdbcTemplate.update("""
                        UPDATE audit_confirmation
                        SET status = 'CONSUMED', consumed_at = ?
                        WHERE confirmation_id = ? AND status = 'APPROVED' AND consumed_at IS NULL
                        """,
                Timestamp.from(consumedAt),
                confirmationId.toString());
    }

    private Optional<ConfirmationRecord> queryOne(String sql, UUID confirmationId) {
        List<ConfirmationRecord> records = jdbcTemplate.query(
                sql,
                this::mapRow,
                confirmationId.toString());
        return records.stream().findFirst();
    }

    private ConfirmationRecord mapRow(ResultSet resultSet, int rowNumber) throws SQLException {
        return new ConfirmationRecord(
                UUID.fromString(resultSet.getString("confirmation_id")),
                UUID.fromString(resultSet.getString("audit_id")),
                resultSet.getString("tool_call_id"),
                resultSet.getString("tenant_id"),
                resultSet.getString("actor_id"),
                resultSet.getString("tool_name"),
                resultSet.getString("canonical_input"),
                resultSet.getString("action_digest"),
                ConfirmationStatus.valueOf(resultSet.getString("status")),
                resultSet.getString("decision_reason"),
                instant(resultSet.getTimestamp("requested_at")),
                instant(resultSet.getTimestamp("decided_at")),
                instant(resultSet.getTimestamp("expires_at")),
                instant(resultSet.getTimestamp("consumed_at")));
    }

    private Instant instant(Timestamp timestamp) {
        return timestamp == null ? null : timestamp.toInstant();
    }
}

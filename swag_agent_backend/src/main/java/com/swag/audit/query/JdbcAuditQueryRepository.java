package com.swag.audit.query;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.util.List;
import java.util.UUID;

/**
 * 审计事件只读查询仓库。
 */
@Repository
public class JdbcAuditQueryRepository {

    private final JdbcTemplate jdbcTemplate;

    public JdbcAuditQueryRepository(JdbcTemplate jdbcTemplate) {
        this.jdbcTemplate = jdbcTemplate;
    }

    public List<AuditEventView> findByAuditId(UUID auditId) {
        return jdbcTemplate.query("""
                        SELECT event_id, audit_id, request_id,
                               trace_id, span_id, parent_span_id,
                               tenant_id, actor_type, actor_id,
                               event_type, execution_status,
                               agent_name, model_name,
                               tool_name, tool_call_id,
                               confirmation_id, action_digest,
                               input_digest, output_digest,
                               event_data, error_code, error_message,
                               occurred_at, recorded_at
                        FROM audit_event
                        WHERE audit_id = ?
                        ORDER BY occurred_at ASC, recorded_at ASC, event_id ASC
                        """,
                this::mapRow,
                auditId.toString());
    }

    private AuditEventView mapRow(ResultSet resultSet, int rowNumber) throws SQLException {
        return new AuditEventView(
                uuid(resultSet.getString("event_id")),
                uuid(resultSet.getString("audit_id")),
                resultSet.getString("request_id"),
                resultSet.getString("trace_id"),
                resultSet.getString("span_id"),
                resultSet.getString("parent_span_id"),
                resultSet.getString("tenant_id"),
                resultSet.getString("actor_type"),
                resultSet.getString("actor_id"),
                resultSet.getString("event_type"),
                resultSet.getString("execution_status"),
                resultSet.getString("agent_name"),
                resultSet.getString("model_name"),
                resultSet.getString("tool_name"),
                resultSet.getString("tool_call_id"),
                uuid(resultSet.getString("confirmation_id")),
                resultSet.getString("action_digest"),
                resultSet.getString("input_digest"),
                resultSet.getString("output_digest"),
                resultSet.getString("event_data"),
                resultSet.getString("error_code"),
                resultSet.getString("error_message"),
                resultSet.getTimestamp("occurred_at").toInstant(),
                resultSet.getTimestamp("recorded_at").toInstant());
    }

    private UUID uuid(String value) {
        return value == null ? null : UUID.fromString(value);
    }
}

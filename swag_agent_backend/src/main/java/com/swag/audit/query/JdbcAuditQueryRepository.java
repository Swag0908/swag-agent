package com.swag.audit.query;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.sql.Timestamp;
import java.time.Instant;
import java.util.Collections;
import java.util.List;
import java.util.UUID;

/**
 * 审计事件只读查询仓库。
 */
@Repository
public class JdbcAuditQueryRepository {

    /** 一条审计链的汇总行（管理端列表用）。 */
    public record ChainSummary(UUID auditId, Instant startedAt, Instant endedAt, long eventCount) {
    }

    /** 请求级事件行：只有这几类事件带 method/path/httpStatus。 */
    public record RequestEvent(UUID auditId, String eventType, String executionStatus,
                               String actorId, String traceId, String eventData) {
    }

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

    /**
     * 最近若干条审计链的汇总（按最后一条事件时间倒序）。
     * <p>
     * audit_event 没有单独的「链」表，链的边界就是 audit_id 的分组。
     */
    public List<ChainSummary> findRecentChains(int limit) {
        return jdbcTemplate.query("""
                        SELECT audit_id,
                               MIN(occurred_at) AS started_at,
                               MAX(occurred_at) AS ended_at,
                               COUNT(*)         AS event_count
                        FROM audit_event
                        GROUP BY audit_id
                        ORDER BY ended_at DESC
                        LIMIT ?
                        """,
                (resultSet, rowNumber) -> new ChainSummary(
                        UUID.fromString(resultSet.getString("audit_id")),
                        instant(resultSet.getTimestamp("started_at")),
                        instant(resultSet.getTimestamp("ended_at")),
                        resultSet.getLong("event_count")),
                limit);
    }

    /**
     * 只取链上的请求级事件（带 method/path/httpStatus 的那三类），
     * 按时间正序返回，供上层还原「谁、请求了什么、最后什么状态」。
     */
    public List<RequestEvent> findRequestEvents(List<UUID> auditIds) {
        if (auditIds == null || auditIds.isEmpty()) {
            return List.of();
        }
        String placeholders = String.join(",", Collections.nCopies(auditIds.size(), "?"));
        Object[] arguments = auditIds.stream().map(UUID::toString).toArray();
        return jdbcTemplate.query("""
                        SELECT audit_id, event_type, execution_status, actor_id, trace_id, event_data
                        FROM audit_event
                        WHERE event_type IN ('REQUEST_RECEIVED', 'REQUEST_COMPLETED', 'REQUEST_FAILED')
                          AND audit_id IN (%s)
                        ORDER BY occurred_at ASC, recorded_at ASC
                        """.formatted(placeholders),
                (resultSet, rowNumber) -> new RequestEvent(
                        UUID.fromString(resultSet.getString("audit_id")),
                        resultSet.getString("event_type"),
                        resultSet.getString("execution_status"),
                        resultSet.getString("actor_id"),
                        resultSet.getString("trace_id"),
                        resultSet.getString("event_data")),
                arguments);
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

    private Instant instant(Timestamp value) {
        return value == null ? null : value.toInstant();
    }
}

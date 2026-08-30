package com.swag.audit.core;

import com.swag.audit.context.AuditContextHolder;
import com.swag.audit.context.AuditRequestContext;
import io.micrometer.tracing.Span;
import io.micrometer.tracing.Tracer;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Component;
import tools.jackson.databind.ObjectMapper;

import java.sql.Timestamp;
import java.time.Instant;
import java.util.Map;
import java.util.UUID;

/**
 * 使用 MySQL 追加写入审计事件。
 */
@Component
public class JdbcAuditRecorder implements AuditRecorder {

    private static final String INSERT_SQL = """
            INSERT INTO audit_event (
                event_id, audit_id, request_id, source_event_id,
                trace_id, span_id, parent_span_id, parent_event_id,
                tenant_id, session_id,
                actor_type, actor_id, actor_display_name,
                event_type, execution_status,
                agent_name, agent_version, model_name,
                tool_name, tool_call_id,
                confirmation_id, action_digest,
                input_ref, input_digest, output_ref, output_digest,
                event_data, error_code, error_message,
                occurred_at, recorded_at, schema_version,
                previous_hash, event_hash
            ) VALUES (
                :eventId, :auditId, :requestId, NULL,
                :traceId, :spanId, :parentSpanId, :parentEventId,
                :tenantId, :sessionId,
                :actorType, :actorId, NULL,
                :eventType, :executionStatus,
                :agentName, :agentVersion, :modelName,
                :toolName, :toolCallId,
                :confirmationId, :actionDigest,
                :inputRef, :inputDigest, :outputRef, :outputDigest,
                :eventData, :errorCode, :errorMessage,
                :occurredAt, :recordedAt, 1,
                NULL, NULL
            )
            """;

    private final NamedParameterJdbcTemplate jdbcTemplate;
    private final ObjectMapper objectMapper;
    private final Tracer tracer;

    public JdbcAuditRecorder(
            NamedParameterJdbcTemplate jdbcTemplate,
            ObjectMapper objectMapper,
            Tracer tracer) {
        this.jdbcTemplate = jdbcTemplate;
        this.objectMapper = objectMapper;
        this.tracer = tracer;
    }

    @Override
    public UUID record(AuditEventCommand command) {
        if (command == null || command.eventType() == null) {
            throw new IllegalArgumentException("audit event type must not be null");
        }

        AuditRequestContext requestContext = AuditContextHolder.current().orElse(null);
        UUID auditId = command.auditIdOverride() != null
                ? command.auditIdOverride()
                : requireAuditId(requestContext);

        Span currentSpan = tracer.currentSpan();
        UUID eventId = UUID.randomUUID();
        Instant now = Instant.now();

        MapSqlParameterSource parameters = new MapSqlParameterSource()
                .addValue("eventId", eventId.toString())
                .addValue("auditId", auditId.toString())
                .addValue("requestId", requestContext == null ? null : requestContext.requestId())
                .addValue("traceId", currentSpan == null ? null : currentSpan.context().traceId())
                .addValue("spanId", currentSpan == null ? null : currentSpan.context().spanId())
                .addValue("parentSpanId", currentSpan == null ? null : currentSpan.context().parentId())
                .addValue("parentEventId", uuid(command.parentEventId()))
                .addValue("tenantId", requestContext == null ? null : requestContext.tenantId())
                .addValue("sessionId", requestContext == null ? null : requestContext.sessionId())
                .addValue("actorType", defaultString(command.actorType(), "SYSTEM"))
                .addValue("actorId", command.actorIdOverride() != null
                        ? command.actorIdOverride()
                        : requestContext == null ? null : requestContext.actorId())
                .addValue("eventType", command.eventType().name())
                .addValue("executionStatus", command.executionStatus())
                .addValue("agentName", command.agentName())
                .addValue("agentVersion", command.agentVersion())
                .addValue("modelName", command.modelName())
                .addValue("toolName", command.toolName())
                .addValue("toolCallId", command.toolCallId())
                .addValue("confirmationId", uuid(command.confirmationId()))
                .addValue("actionDigest", command.actionDigest())
                .addValue("inputRef", command.inputRef())
                .addValue("inputDigest", command.inputDigest())
                .addValue("outputRef", command.outputRef())
                .addValue("outputDigest", command.outputDigest())
                .addValue("eventData", toJson(command.eventData()))
                .addValue("errorCode", command.errorCode())
                .addValue("errorMessage", truncate(command.errorMessage(), 4000))
                .addValue("occurredAt", Timestamp.from(now))
                .addValue("recordedAt", Timestamp.from(now));

        jdbcTemplate.update(INSERT_SQL, parameters);
        return eventId;
    }

    private UUID requireAuditId(AuditRequestContext context) {
        if (context == null || context.auditId() == null) {
            throw new IllegalStateException("No audit context is active");
        }
        return context.auditId();
    }

    private String toJson(Map<String, ?> eventData) {
        try {
            return objectMapper.writeValueAsString(eventData == null ? Map.of() : eventData);
        }
        catch (Exception exception) {
            throw new IllegalArgumentException("Cannot serialize audit event data", exception);
        }
    }

    private String uuid(UUID value) {
        return value == null ? null : value.toString();
    }

    private String defaultString(String value, String defaultValue) {
        return value == null || value.isBlank() ? defaultValue : value;
    }

    private String truncate(String value, int maximumLength) {
        if (value == null || value.length() <= maximumLength) {
            return value;
        }
        return value.substring(0, maximumLength);
    }
}

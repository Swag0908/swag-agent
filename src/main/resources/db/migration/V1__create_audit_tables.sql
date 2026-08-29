CREATE TABLE audit_event (
    event_id            CHAR(36)      NOT NULL,
    audit_id            CHAR(36)      NOT NULL,
    request_id          VARCHAR(128)  NULL,
    source_event_id     VARCHAR(128)  NULL,

    trace_id            VARCHAR(64)   NULL,
    span_id             VARCHAR(32)   NULL,
    parent_span_id      VARCHAR(32)   NULL,
    parent_event_id     CHAR(36)      NULL,

    tenant_id           VARCHAR(128)  NULL,
    session_id          VARCHAR(128)  NULL,

    actor_type          VARCHAR(32)   NOT NULL,
    actor_id            VARCHAR(256)  NULL,
    actor_display_name  VARCHAR(256)  NULL,

    event_type          VARCHAR(64)   NOT NULL,
    execution_status    VARCHAR(32)   NULL,

    agent_name          VARCHAR(128)  NULL,
    agent_version       VARCHAR(64)   NULL,
    model_name          VARCHAR(128)  NULL,

    tool_name           VARCHAR(128)  NULL,
    tool_call_id        VARCHAR(128)  NULL,

    confirmation_id     CHAR(36)      NULL,
    action_digest       CHAR(64)      NULL,

    input_ref           VARCHAR(512)  NULL,
    input_digest        CHAR(64)      NULL,
    output_ref          VARCHAR(512)  NULL,
    output_digest       CHAR(64)      NULL,

    event_data          JSON          NULL,

    error_code          VARCHAR(128)  NULL,
    error_message       TEXT          NULL,

    occurred_at         DATETIME(6)   NOT NULL,
    recorded_at         DATETIME(6)   NOT NULL,

    schema_version      INT           NOT NULL DEFAULT 1,

    previous_hash       CHAR(64)      NULL,
    event_hash          CHAR(64)      NULL,

    PRIMARY KEY (event_id),
    UNIQUE KEY uk_audit_source_event (source_event_id),
    KEY idx_audit_event_audit_time (audit_id, occurred_at),
    KEY idx_audit_event_trace (trace_id),
    KEY idx_audit_event_user_time (tenant_id, actor_id, occurred_at),
    KEY idx_audit_event_tool_call (tool_call_id),
    KEY idx_audit_event_confirmation (confirmation_id)
);

CREATE TABLE audit_payload (
    payload_id          CHAR(36)       NOT NULL,
    audit_id            CHAR(36)       NOT NULL,
    payload_type        VARCHAR(32)    NOT NULL,
    storage_uri         VARCHAR(1024)  NOT NULL,
    content_digest      CHAR(64)       NOT NULL,
    media_type          VARCHAR(128)   NULL,
    size_bytes          BIGINT         NULL,
    encryption_key_id   VARCHAR(256)   NULL,
    redaction_version   VARCHAR(64)    NULL,
    created_at          DATETIME(6)    NOT NULL,
    expires_at          DATETIME(6)    NULL,

    PRIMARY KEY (payload_id),
    KEY idx_audit_payload_audit (audit_id),
    KEY idx_audit_payload_expires (expires_at)
);

CREATE TABLE audit_request_summary (
    audit_id             CHAR(36)      NOT NULL,
    request_id           VARCHAR(128)  NULL,
    tenant_id            VARCHAR(128)  NULL,
    user_id              VARCHAR(256)  NULL,
    trace_id             VARCHAR(64)   NULL,

    request_type         VARCHAR(64)   NULL,
    request_summary      TEXT          NULL,

    final_status         VARCHAR(32)   NULL,
    risk_level           VARCHAR(16)   NULL,

    tool_call_count      INT           NOT NULL DEFAULT 0,
    confirmation_count   INT           NOT NULL DEFAULT 0,
    failed_event_count   INT           NOT NULL DEFAULT 0,

    started_at           DATETIME(6)   NULL,
    completed_at         DATETIME(6)   NULL,
    duration_ms          BIGINT        NULL,

    last_event_at        DATETIME(6)   NULL,
    retention_until      DATETIME(6)   NULL,

    PRIMARY KEY (audit_id),
    KEY idx_audit_summary_user_time (tenant_id, user_id, started_at),
    KEY idx_audit_summary_status_time (final_status, started_at),
    KEY idx_audit_summary_trace (trace_id)
);

CREATE TABLE audit_confirmation (
    confirmation_id     CHAR(36)      NOT NULL,
    audit_id            CHAR(36)      NOT NULL,
    tool_call_id        VARCHAR(128)  NULL,
    tenant_id           VARCHAR(128)  NULL,
    actor_id            VARCHAR(256)  NULL,
    tool_name            VARCHAR(128)  NOT NULL,
    canonical_input      LONGTEXT      NOT NULL,
    action_digest        CHAR(64)      NOT NULL,
    status               VARCHAR(32)   NOT NULL,
    decision_reason      VARCHAR(512)  NULL,
    requested_at         DATETIME(6)   NOT NULL,
    decided_at           DATETIME(6)   NULL,
    expires_at           DATETIME(6)   NOT NULL,
    consumed_at          DATETIME(6)   NULL,

    PRIMARY KEY (confirmation_id),
    KEY idx_audit_confirmation_audit (audit_id),
    KEY idx_audit_confirmation_status_expiry (status, expires_at)
);

package com.swag.audit.core;

import java.util.UUID;

/**
 * 审计事件的唯一写入口。
 */
public interface AuditRecorder {

    /**
     * 追加一条不可变审计事件。
     *
     * @return 新事件的 event_id
     */
    UUID record(AuditEventCommand command);
}

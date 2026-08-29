package com.swag.audit.web;

import com.swag.audit.query.AuditEventView;

/**
 * 包含 Zipkin 跳转地址的审计事件响应。
 */
public record AuditEventResponse(
        AuditEventView event,
        String zipkinTraceUrl) {
}

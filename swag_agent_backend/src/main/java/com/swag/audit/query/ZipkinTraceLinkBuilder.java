package com.swag.audit.query;

import com.swag.audit.config.AuditProperties;
import org.springframework.stereotype.Component;

/**
 * 根据 trace_id 生成 Zipkin UI 链接。
 */
@Component
public class ZipkinTraceLinkBuilder {

    private final AuditProperties properties;

    public ZipkinTraceLinkBuilder(AuditProperties properties) {
        this.properties = properties;
    }

    public String build(String traceId) {
        if (traceId == null || traceId.isBlank()) {
            return null;
        }
        String baseUrl = properties.getZipkinUiBaseUrl().replaceAll("/+$", "");
        return baseUrl + "/zipkin/traces/" + traceId;
    }
}

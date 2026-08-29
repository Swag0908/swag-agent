package com.swag.audit.tool;

import com.swag.audit.confirmation.ConfirmationService;
import com.swag.audit.config.AuditProperties;
import com.swag.audit.core.AuditDigest;
import com.swag.audit.core.AuditRecorder;
import io.micrometer.observation.ObservationRegistry;
import org.springframework.ai.tool.ToolCallback;
import org.springframework.stereotype.Component;

import java.util.Arrays;

/**
 * 将普通 Spring AI ToolCallback 统一包装为可审计、可确认的 ToolCallback。
 */
@Component
public class AuditToolCallbackFactory {

    private final AuditRecorder auditRecorder;
    private final AuditDigest auditDigest;
    private final ConfirmationService confirmationService;
    private final ObservationRegistry observationRegistry;
    private final AuditProperties auditProperties;

    public AuditToolCallbackFactory(
            AuditRecorder auditRecorder,
            AuditDigest auditDigest,
            ConfirmationService confirmationService,
            ObservationRegistry observationRegistry,
            AuditProperties auditProperties) {
        this.auditRecorder = auditRecorder;
        this.auditDigest = auditDigest;
        this.confirmationService = confirmationService;
        this.observationRegistry = observationRegistry;
        this.auditProperties = auditProperties;
    }

    public ToolCallback[] wrap(ToolCallback... callbacks) {
        return Arrays.stream(callbacks)
                .map(callback -> new AuditingToolCallback(
                        callback,
                        auditRecorder,
                        auditDigest,
                        confirmationService,
                        observationRegistry,
                        auditProperties))
                .toArray(ToolCallback[]::new);
    }
}

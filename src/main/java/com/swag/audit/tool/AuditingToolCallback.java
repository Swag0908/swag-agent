package com.swag.audit.tool;

import com.swag.audit.confirmation.ConfirmationRequiredException;
import com.swag.audit.confirmation.ConfirmationService;
import com.swag.audit.config.AuditProperties;
import com.swag.audit.context.AuditContextHolder;
import com.swag.audit.core.AuditDigest;
import com.swag.audit.core.AuditEventCommand;
import com.swag.audit.core.AuditEventType;
import com.swag.audit.core.AuditRecorder;
import io.micrometer.observation.Observation;
import io.micrometer.observation.ObservationRegistry;
import org.springframework.ai.chat.model.ToolContext;
import org.springframework.ai.tool.ToolCallback;
import org.springframework.ai.tool.definition.ToolDefinition;
import org.springframework.ai.tool.metadata.ToolMetadata;
import org.springframework.ai.tool.observation.ToolCallingObservationContext;

import java.util.Map;
import java.util.LinkedHashMap;
import java.util.UUID;

/**
 * 在不修改具体 @Tool 方法的前提下，统一记录工具调用并执行确认检查。
 */
public class AuditingToolCallback implements ToolCallback {

    private final ToolCallback delegate;
    private final AuditRecorder auditRecorder;
    private final AuditDigest auditDigest;
    private final ConfirmationService confirmationService;
    private final ObservationRegistry observationRegistry;
    private final AuditProperties auditProperties;

    public AuditingToolCallback(
            ToolCallback delegate,
            AuditRecorder auditRecorder,
            AuditDigest auditDigest,
            ConfirmationService confirmationService,
            ObservationRegistry observationRegistry,
            AuditProperties auditProperties) {
        this.delegate = delegate;
        this.auditRecorder = auditRecorder;
        this.auditDigest = auditDigest;
        this.confirmationService = confirmationService;
        this.observationRegistry = observationRegistry;
        this.auditProperties = auditProperties;
    }

    @Override
    public ToolDefinition getToolDefinition() {
        return delegate.getToolDefinition();
    }

    @Override
    public ToolMetadata getToolMetadata() {
        return delegate.getToolMetadata();
    }

    @Override
    public String call(String input) {
        return call(input, new ToolContext(Map.of()));
    }

    @Override
    public String call(String input, ToolContext toolContext) {
        String toolName = delegate.getToolDefinition().name();
        String toolCallId = currentToolCallId();
        String inputDigest = auditDigest.sha256(input);
        String canonicalInput = auditDigest.canonicalizeJson(input);
        String actionDigest = auditDigest.actionDigest(toolName, input);
        UUID requestConfirmationId = currentConfirmationId();

        auditRecorder.record(AuditEventCommand.builder()
                .eventType(AuditEventType.TOOL_CALL_REQUESTED)
                .executionStatus("REQUESTED")
                .actorType("AGENT")
                .toolName(toolName)
                .toolCallId(toolCallId)
                .confirmationId(requestConfirmationId)
                .actionDigest(actionDigest)
                .inputDigest(inputDigest)
                .eventData(toolInputData(input))
                .build());

        UUID consumedConfirmationId = verifyConfirmationIfRequired(
                toolName,
                toolCallId,
                canonicalInput,
                actionDigest);

        auditRecorder.record(AuditEventCommand.builder()
                .eventType(AuditEventType.TOOL_CALL_STARTED)
                .executionStatus("STARTED")
                .actorType("AGENT")
                .toolName(toolName)
                .toolCallId(toolCallId)
                .confirmationId(consumedConfirmationId)
                .actionDigest(actionDigest)
                .inputDigest(inputDigest)
                .build());

        try {
            // 执行工具
            String output = delegate.call(input, toolContext);
            auditRecorder.record(AuditEventCommand.builder()
                    .eventType(AuditEventType.TOOL_CALL_SUCCEEDED)
                    .executionStatus("SUCCEEDED")
                    .actorType("AGENT")
                    .toolName(toolName)
                    .toolCallId(toolCallId)
                    .confirmationId(consumedConfirmationId)
                    .actionDigest(actionDigest)
                    .inputDigest(inputDigest)
                    .outputDigest(auditDigest.sha256(output))
                    .eventData(toolOutputData(output))
                    .build());
            return output;
        }
        catch (Exception exception) {
            auditRecorder.record(AuditEventCommand.builder()
                    .eventType(AuditEventType.TOOL_CALL_FAILED)
                    .executionStatus("FAILED")
                    .actorType("AGENT")
                    .toolName(toolName)
                    .toolCallId(toolCallId)
                    .confirmationId(consumedConfirmationId)
                    .actionDigest(actionDigest)
                    .inputDigest(inputDigest)
                    .errorCode(exception.getClass().getSimpleName())
                    .errorMessage(exception.getMessage())
                    .build());
            throw exception;
        }
    }

    private UUID verifyConfirmationIfRequired(
            String toolName,
            String toolCallId,
            String canonicalInput,
            String actionDigest) {
        if (!confirmationService.requiresConfirmation(toolName)) {
            return null;
        }

        UUID confirmationId = currentConfirmationId();
        if (confirmationId == null) {
            ConfirmationRequiredException exception =
                    confirmationService.requestConfirmation(
                            toolName,
                            toolCallId,
                            canonicalInput,
                            actionDigest);
            throw exception;
        }

        confirmationService.consumeApproval(
                confirmationId,
                toolName,
                actionDigest);
        return confirmationId;
    }

    private String currentToolCallId() {
        Observation current = observationRegistry.getCurrentObservation();
        if (current != null
                && current.getContext() instanceof ToolCallingObservationContext context
                && context.getToolCallId() != null) {
            return context.getToolCallId();
        }
        return UUID.randomUUID().toString();
    }

    private UUID currentConfirmationId() {
        return AuditContextHolder.current()
                .map(context -> context.confirmationId())
                .orElse(null);
    }

    private Map<String, Object> toolInputData(String input) {
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("inputLength", input == null ? 0 : input.length());
        if (auditProperties.isIncludeToolContent()) {
            data.put("input", input);
        }
        return data;
    }

    private Map<String, Object> toolOutputData(String output) {
        Map<String, Object> data = new LinkedHashMap<>();
        data.put("outputLength", output == null ? 0 : output.length());
        if (auditProperties.isIncludeToolContent()) {
            data.put("output", output);
        }
        return data;
    }
}

package com.swag.audit.advisor;

import com.swag.audit.confirmation.ConfirmationRequiredException;
import com.swag.audit.context.AuditContextHolder;
import com.swag.audit.core.AuditDigest;
import com.swag.audit.core.AuditEventCommand;
import com.swag.audit.core.AuditEventType;
import com.swag.audit.core.AuditRecorder;
import org.springframework.ai.chat.client.ChatClientRequest;
import org.springframework.ai.chat.client.ChatClientResponse;
import org.springframework.ai.chat.client.advisor.api.CallAdvisor;
import org.springframework.ai.chat.client.advisor.api.CallAdvisorChain;
import org.springframework.core.Ordered;
import org.springframework.stereotype.Component;

import java.util.Map;

/**
 * 记录一次同步 ChatClient/Agent 调用的开始、完成、等待确认和失败事件。
 */
@Component
public class AuditAdvisor implements CallAdvisor {

    private final AuditRecorder auditRecorder;
    private final AuditDigest auditDigest;

    public AuditAdvisor(
            AuditRecorder auditRecorder,
            AuditDigest auditDigest) {
        this.auditRecorder = auditRecorder;
        this.auditDigest = auditDigest;
    }

    @Override
    public ChatClientResponse adviseCall(
            ChatClientRequest request,
            CallAdvisorChain chain) {
        String auditId = AuditContextHolder.current()
                .orElseThrow(() -> new IllegalStateException("No audit context is active"))
                .auditId()
                .toString();
        String modelName = request.prompt().getOptions() == null
                ? null
                : request.prompt().getOptions().getModel();

        ChatClientRequest auditedRequest = request.mutate()
                .context("audit_id", auditId)
                .build();

        auditRecorder.record(AuditEventCommand.builder()
                .eventType(AuditEventType.AGENT_STARTED)
                .executionStatus("STARTED")
                .actorType("AGENT")
                .agentName("chatClient")
                .modelName(modelName)
                .inputDigest(auditDigest.sha256(request.prompt().getContents()))
                .eventData(Map.of("advisor", getName()))
                .build());

        try {
            ChatClientResponse response = chain.nextCall(auditedRequest);
            // 还得继续调用别的 chain 或者 tool
            String output = response.chatResponse() == null
                    || response.chatResponse().getResult() == null
                    ? ""
                    : response.chatResponse().getResult().getOutput().getText();

            auditRecorder.record(AuditEventCommand.builder()
                    .eventType(AuditEventType.AGENT_COMPLETED)
                    .executionStatus("SUCCEEDED")
                    .actorType("AGENT")
                    .agentName("chatClient")
                    .modelName(modelName)
                    .outputDigest(auditDigest.sha256(output))
                    .build());

            return response.mutate()
                    .context("audit_id", auditId)
                    .build();
        }
        catch (ConfirmationRequiredException exception) {
            auditRecorder.record(AuditEventCommand.builder()
                    .eventType(AuditEventType.AGENT_WAITING_CONFIRMATION)
                    .executionStatus("WAITING_CONFIRMATION")
                    .actorType("AGENT")
                    .agentName("chatClient")
                    .modelName(modelName)
                    .toolName(exception.getToolName())
                    .confirmationId(exception.getConfirmationId())
                    .build());
            throw exception;
        }
        catch (Exception exception) {
            auditRecorder.record(AuditEventCommand.builder()
                    .eventType(AuditEventType.AGENT_FAILED)
                    .executionStatus("FAILED")
                    .actorType("AGENT")
                    .agentName("chatClient")
                    .modelName(modelName)
                    .errorCode(exception.getClass().getSimpleName())
                    .errorMessage(exception.getMessage())
                    .build());
            throw exception;
        }
    }

    @Override
    public String getName() {
        return "auditAdvisor";
    }

    @Override
    public int getOrder() {
        return Ordered.HIGHEST_PRECEDENCE + 100;
    }
}

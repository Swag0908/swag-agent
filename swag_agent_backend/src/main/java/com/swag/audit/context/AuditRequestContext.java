package com.swag.audit.context;

import java.util.UUID;

/**
 * 当前同步请求的审计上下文。
 *
 * @param auditId 一次用户请求完整审计链的标识
 * @param requestId 当前 HTTP 请求标识
 * @param tenantId 当前租户标识
 * @param actorId 当前用户标识
 * @param sessionId 当前会话标识
 * @param confirmationId 本次重试携带的确认标识
 * @param conversationId 本次请求所属的聊天会话 id（非聊天请求为 null）；
 *                       删除会话时按它回收该会话的审计记录
 */
public record AuditRequestContext(
        UUID auditId,
        String requestId,
        String tenantId,
        String actorId,
        String sessionId,
        UUID confirmationId,
        String conversationId) {
}

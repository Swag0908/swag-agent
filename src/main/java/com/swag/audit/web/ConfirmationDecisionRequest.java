package com.swag.audit.web;

/**
 * 用户确认决策请求。
 *
 * @param decision APPROVED 或 DENIED
 * @param reason 决策原因，可为空
 */
public record ConfirmationDecisionRequest(
        String decision,
        String reason) {
}

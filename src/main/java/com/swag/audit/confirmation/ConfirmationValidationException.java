package com.swag.audit.confirmation;

/**
 * 确认不存在、状态不正确、已过期或与待执行动作不匹配。
 */
public class ConfirmationValidationException extends RuntimeException {

    public ConfirmationValidationException(String message) {
        super(message);
    }
}

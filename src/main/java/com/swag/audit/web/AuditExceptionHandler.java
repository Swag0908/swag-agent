package com.swag.audit.web;

import com.swag.audit.confirmation.ConfirmationRequiredException;
import com.swag.audit.confirmation.ConfirmationValidationException;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

import java.time.Instant;
import java.util.LinkedHashMap;
import java.util.Map;

/**
 * 将确认状态转换为稳定的 HTTP 响应。
 */
@RestControllerAdvice
public class AuditExceptionHandler {

    @ExceptionHandler(ConfirmationRequiredException.class)
    public ResponseEntity<Map<String, Object>> handleRequired(
            ConfirmationRequiredException exception) {
        Map<String, Object> body = new LinkedHashMap<>();
        body.put("code", "CONFIRMATION_REQUIRED");
        body.put("message", exception.getMessage());
        body.put("auditId", exception.getAuditId());
        body.put("confirmationId", exception.getConfirmationId());
        body.put("toolName", exception.getToolName());
        body.put("requestedAt", exception.getValidity().requestedAt());
        body.put("expiresAt", exception.getValidity().expiresAt());
        body.put(
                "nextStep",
                "Approve the confirmation, then retry the original request with header "
                        + AuditContextFilter.CONFIRMATION_ID_HEADER);
        return ResponseEntity.status(HttpStatus.CONFLICT).body(body);
    }

    @ExceptionHandler(ConfirmationValidationException.class)
    public ResponseEntity<Map<String, Object>> handleValidation(
            ConfirmationValidationException exception) {
        return ResponseEntity.status(HttpStatus.CONFLICT).body(Map.of(
                "code", "CONFIRMATION_INVALID",
                "message", exception.getMessage(),
                "timestamp", Instant.now()));
    }
}

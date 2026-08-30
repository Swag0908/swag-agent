package com.swag.audit.web;

import com.swag.audit.confirmation.ConfirmationRecord;
import com.swag.audit.confirmation.ConfirmationService;
import com.swag.audit.confirmation.ConfirmationStatus;
import com.swag.audit.confirmation.ConfirmationValidationException;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

import java.util.Locale;
import java.util.UUID;

/**
 * 用户批准或拒绝高风险工具调用的 API。
 */
@RestController
@RequestMapping("/audit/confirmations")
public class ConfirmationController {

    private final ConfirmationService confirmationService;

    public ConfirmationController(ConfirmationService confirmationService) {
        this.confirmationService = confirmationService;
    }

    @GetMapping("/{confirmationId}")
    public ConfirmationResponse find(
            @PathVariable UUID confirmationId) {
        return ConfirmationResponse.from(
                confirmationService.find(confirmationId)
                        .orElseThrow(() -> new ConfirmationValidationException(
                                "Confirmation not found")));
    }

    @PostMapping("/{confirmationId}/decision")
    public ConfirmationResponse decide(
            @PathVariable UUID confirmationId,
            @RequestBody ConfirmationDecisionRequest request) {
        if (request == null || request.decision() == null) {
            throw new ConfirmationValidationException("Decision must not be null");
        }

        ConfirmationStatus decision;
        try {
            decision = ConfirmationStatus.valueOf(
                    request.decision().trim().toUpperCase(Locale.ROOT));
        }
        catch (IllegalArgumentException exception) {
            throw new ConfirmationValidationException(
                    "Decision must be APPROVED or DENIED");
        }

        ConfirmationRecord result = confirmationService.decide(
                confirmationId,
                decision,
                request.reason());
        return ConfirmationResponse.from(result);
    }
}

package com.swag.audit.core;

import org.junit.jupiter.api.Test;

import static org.assertj.core.api.Assertions.assertThat;

class AuditDigestTests {

    private final AuditDigest auditDigest = new AuditDigest();

    @Test
    void actionDigestIgnoresJsonObjectFieldOrder() {
        String first = auditDigest.actionDigest(
                "sendEmail",
                """
                {"recipient":"user@example.com","subject":"hello"}
                """);
        String second = auditDigest.actionDigest(
                "sendEmail",
                """
                {"subject":"hello","recipient":"user@example.com"}
                """);

        assertThat(first).isEqualTo(second);
    }

    @Test
    void sha256ProducesLowercaseHexDigest() {
        assertThat(auditDigest.sha256("audit"))
                .matches("[0-9a-f]{64}");
    }
}

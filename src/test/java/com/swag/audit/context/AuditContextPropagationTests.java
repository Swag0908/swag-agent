package com.swag.audit.context;

import io.micrometer.context.ContextRegistry;
import io.micrometer.context.ThreadLocalAccessor;
import org.junit.jupiter.api.AfterAll;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Hooks;
import reactor.core.scheduler.Scheduler;
import reactor.core.scheduler.Schedulers;

import java.util.UUID;
import java.util.concurrent.atomic.AtomicReference;

import static org.assertj.core.api.Assertions.assertThat;

class AuditContextPropagationTests {

    private static final Scheduler WORKER = Schedulers.newSingle("audit-context-test");
    private static ThreadLocalAccessor<?> previousAccessor;
    private static boolean automaticPropagationPreviouslyEnabled;

    @BeforeAll
    static void enableContextPropagation() {
        ContextRegistry registry = ContextRegistry.getInstance();
        previousAccessor = registry.getThreadLocalAccessors().stream()
                .filter(accessor -> AuditContextThreadLocalAccessor.KEY.equals(accessor.key()))
                .findFirst()
                .orElse(null);
        automaticPropagationPreviouslyEnabled = Hooks.isAutomaticContextPropagationEnabled();
        registry.registerThreadLocalAccessor(
                new AuditContextThreadLocalAccessor());
        Hooks.enableAutomaticContextPropagation();
    }

    @AfterAll
    static void cleanUpContextPropagation() {
        WORKER.dispose();
        ContextRegistry registry = ContextRegistry.getInstance();
        registry.removeThreadLocalAccessor(AuditContextThreadLocalAccessor.KEY);
        if (previousAccessor != null) {
            registry.registerThreadLocalAccessor(previousAccessor);
        }
        if (!automaticPropagationPreviouslyEnabled) {
            Hooks.disableAutomaticContextPropagation();
        }
    }

    @Test
    void restoresAuditContextOnReactorWorkerThread() {
        AuditRequestContext expected = new AuditRequestContext(
                UUID.randomUUID(),
                UUID.randomUUID().toString(),
                "tenant-1",
                "actor-1",
                "session-1",
                null);
        AtomicReference<String> executionThread = new AtomicReference<>();

        AuditRequestContext actual;
        try (AuditContextHolder.Scope ignored = AuditContextHolder.open(expected)) {
            Flux<AuditRequestContext> workerCall = Flux.defer(() -> {
                executionThread.set(Thread.currentThread().getName());
                return Flux.just(AuditContextHolder.current().orElseThrow());
            }).subscribeOn(WORKER);

            actual = AuditContextHolder.propagate(workerCall).blockFirst();
        }

        assertThat(actual).isEqualTo(expected);
        assertThat(executionThread.get()).startsWith("audit-context-test");
        assertThat(AuditContextHolder.current()).isEmpty();
    }
}

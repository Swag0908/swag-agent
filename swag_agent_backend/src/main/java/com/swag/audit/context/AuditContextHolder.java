package com.swag.audit.context;

import reactor.core.publisher.Flux;

import java.util.Objects;
import java.util.Optional;

/**
 * 保存当前调用链的审计上下文。同步调用直接使用 ThreadLocal，
 * Reactor 调用通过 {@link #propagate(Flux)} 写入 Reactor Context，再由
 * Micrometer Context Propagation 在工作线程恢复。
 */
public final class AuditContextHolder {

    private static final ThreadLocal<AuditRequestContext> CONTEXT = new ThreadLocal<>();

    private AuditContextHolder() {
    }

    public static Optional<AuditRequestContext> current() {
        return Optional.ofNullable(CONTEXT.get());
    }

    /**
     * 捕获当前审计上下文并传递给延迟执行的 Reactor 流。
     */
    public static <T> Flux<T> propagate(Flux<T> publisher) {
        Objects.requireNonNull(publisher, "publisher must not be null");
        AuditRequestContext context = current()
                .orElseThrow(() -> new IllegalStateException("No audit context is active"));
        return publisher.contextWrite(reactorContext -> reactorContext.put(
                AuditContextThreadLocalAccessor.KEY,
                context));
    }

    public static Scope open(AuditRequestContext context) {
        AuditRequestContext previous = CONTEXT.get();
        CONTEXT.set(context);
        return () -> {
            if (previous == null) {
                CONTEXT.remove();
            }
            else {
                CONTEXT.set(previous);
            }
        };
    }

    static void set(AuditRequestContext context) {
        CONTEXT.set(context);
    }

    static void clear() {
        CONTEXT.remove();
    }

    @FunctionalInterface
    public interface Scope extends AutoCloseable {
        @Override
        void close();
    }
}

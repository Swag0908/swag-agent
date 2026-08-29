package com.swag.audit.context;

import java.util.Optional;

/**
 * 保存当前同步调用链的审计上下文。
 * <p>
 * 当前项目使用同步 ChatClient.call()，因此使用 ThreadLocal。若后续改为 stream()、
 * Reactor 或 @Async，需要改用 Micrometer Context Propagation 传递上下文。
 */
public final class AuditContextHolder {

    private static final ThreadLocal<AuditRequestContext> CONTEXT = new ThreadLocal<>();

    private AuditContextHolder() {
    }

    public static Optional<AuditRequestContext> current() {
        return Optional.ofNullable(CONTEXT.get());
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

    @FunctionalInterface
    public interface Scope extends AutoCloseable {
        @Override
        void close();
    }
}

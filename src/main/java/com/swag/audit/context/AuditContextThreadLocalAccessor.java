package com.swag.audit.context;

import io.micrometer.context.ThreadLocalAccessor;

/**
 * Reactor Context 与审计 ThreadLocal 之间的唯一桥接。
 */
public final class AuditContextThreadLocalAccessor
        implements ThreadLocalAccessor<AuditRequestContext> {

    static final String KEY = AuditContextHolder.class.getName();

    @Override
    public Object key() {
        return KEY;
    }

    @Override
    public AuditRequestContext getValue() {
        return AuditContextHolder.current().orElse(null);
    }

    @Override
    public void setValue(AuditRequestContext value) {
        AuditContextHolder.set(value);
    }

    @Override
    public void setValue() {
        AuditContextHolder.clear();
    }
}

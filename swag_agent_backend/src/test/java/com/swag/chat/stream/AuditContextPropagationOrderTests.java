package com.swag.chat.stream;

import com.swag.audit.context.AuditContextHolder;
import com.swag.audit.context.AuditRequestContext;
import com.swag.audit.context.AuditContextThreadLocalAccessor;
import io.micrometer.context.ContextRegistry;
import org.junit.jupiter.api.BeforeAll;
import org.junit.jupiter.api.Test;
import reactor.core.publisher.Flux;
import reactor.core.publisher.Mono;

import java.util.UUID;
import java.util.concurrent.atomic.AtomicReference;

import static org.junit.jupiter.api.Assertions.assertEquals;

/**
 * 审计上下文与「请求组装时机」的关系测试。
 *
 * <p><b>为什么要有这个测试</b>：线上出现过 {@code event:error "No audit context is active"}。
 * 原因是「组装 ChatClient 请求」这个动作发生在审计上下文之外——advisor 里要读
 * {@code AuditContextHolder}，读不到就抛异常。
 *
 * <p>结论被固化成两条：
 * <ol>
 *   <li>在 {@code AuditContextHolder.propagate(...)} 之外直接组装 → 组装时没有上下文（错误做法）；</li>
 *   <li>用 {@code Flux.defer(...)} 推迟到订阅时组装 → 订阅发生在 propagate 的上下文之内，
 *       上下文可用（正确做法）。</li>
 * </ol>
 */
class AuditContextPropagationOrderTests {

    @BeforeAll
    static void registerAccessor() {
        // 与 AuditConfiguration 一样，把审计上下文接到 Reactor Context 上
        ContextRegistry.getInstance().registerThreadLocalAccessor(
                new AuditContextThreadLocalAccessor());
    }

    private static AuditRequestContext context(UUID auditId) {
        return new AuditRequestContext(auditId, "req", "default", "7", null, null, "8");
    }

    /** 模拟 advisor 里那句 AuditContextHolder.current().orElseThrow(...)。 */
    private static String requireAuditId() {
        return AuditContextHolder.current()
                .orElseThrow(() -> new IllegalStateException("No audit context is active"))
                .auditId()
                .toString();
    }

    /** 模拟「组装请求」：真实代码里这一步会经过 advisor 链。 */
    private static Mono<String> assembleRequest() {
        return Mono.fromSupplier(AuditContextPropagationOrderTests::requireAuditId);
    }

    @Test
    void assemblingInsidePropagatedContextWorks() {
        UUID auditId = UUID.randomUUID();
        AtomicReference<String> seen = new AtomicReference<>();

        try (AuditContextHolder.Scope ignored = AuditContextHolder.open(context(auditId))) {
            // 正确的写法：defer 让组装发生在订阅时，而订阅在 propagate 的上下文之内
            Flux<String> events = AuditContextHolder.propagate(
                    Flux.defer(AuditContextPropagationOrderTests::assembleRequest));
            seen.set(events.blockLast(java.time.Duration.ofSeconds(5)));
        }

        assertEquals(auditId.toString(), seen.get(), "订阅时组装应能读到审计上下文");
    }

}

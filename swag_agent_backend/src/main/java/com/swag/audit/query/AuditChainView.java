package com.swag.audit.query;

import java.time.Instant;
import java.util.UUID;

/**
 * 管理端「调用链」列表的一行：一条审计链（= 一次用户请求）的汇总。
 *
 * @param auditId        审计链标识，也是 {@code GET /audit/events/{auditId}} 的入参
 * @param startedAt      链上第一条事件时间
 * @param endedAt        链上最后一条事件时间
 * @param eventCount     链上事件总数
 * @param actorId        发起人用户 ID（取自链上 REQUEST_RECEIVED 事件的 actor_id）
 * @param actorName      发起人用户名（查不到时回退成 actorId 本身，如 anonymous/SYSTEM）
 * @param method         请求方法（GET/POST/…）
 * @param path           请求路径
 * @param httpStatus     最终 HTTP 状态码
 * @param status         最终执行状态：SUCCEEDED / REJECTED / FAILED / WAITING_CONFIRMATION / IN_PROGRESS
 * @param traceId        Zipkin trace id
 * @param zipkinTraceUrl 同源相对地址 {@code /zipkin/traces/{traceId}}，需管理员登录态才能打开
 */
public record AuditChainView(
        UUID auditId,
        Instant startedAt,
        Instant endedAt,
        long eventCount,
        String actorId,
        String actorName,
        String method,
        String path,
        Integer httpStatus,
        String status,
        String traceId,
        String zipkinTraceUrl) {
}

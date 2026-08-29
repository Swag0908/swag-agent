package com.swag.entity;

import lombok.Data;

import java.time.OffsetDateTime;
import java.util.UUID;

/**
 * 审计请求汇总数据对象。
 * <p>
 * 用于快速查询一次用户请求的最终状态和统计信息。该对象是根据审计事件聚合得到的查询视图，
 * 不是不可变的原始审计证据；数据丢失时应能够通过审计事件重新构建。
 */
@Data
public class AuditRequestSummaryDO {
    /** 一次用户请求完整审计链的唯一标识。 */
    private UUID auditId;

    /** 业务请求唯一标识，用于幂等控制和请求定位。 */
    private String requestId;

    /** 请求所属租户标识，用于多租户数据隔离。 */
    private String tenantId;

    /** 发起请求的用户唯一标识。 */
    private String userId;

    /** 请求对应的主 Zipkin Trace 标识。 */
    private String traceId;

    /** 请求业务类型，例如 CHAT、TASK_EXECUTION 或 WORKFLOW。 */
    private String requestType;

    /** 脱敏后的请求内容摘要，用于审计列表展示和检索。 */
    private String requestSummary;

    /** 请求最终状态，例如 SUCCEEDED、FAILED、CANCELLED 或 REJECTED。 */
    private String finalStatus;

    /** 请求风险等级，例如 LOW、MEDIUM、HIGH 或 CRITICAL。 */
    private String riskLevel;

    /** 本次请求产生的工具调用总数。 */
    private Integer toolCallCount;

    /** 本次请求产生的用户确认流程总数。 */
    private Integer confirmationCount;

    /** 本次请求中执行失败的审计事件总数。 */
    private Integer failedEventCount;

    /** 请求开始执行的时间。 */
    private OffsetDateTime startedAt;

    /** 请求结束执行的时间。 */
    private OffsetDateTime completedAt;

    /** 请求从开始到结束的总耗时，单位为毫秒。 */
    private Long durationMs;

    /** 当前审计链最近一次产生事件的时间。 */
    private OffsetDateTime lastEventAt;

    /** 该请求审计数据的保留截止时间。 */
    private OffsetDateTime retentionUntil;
}

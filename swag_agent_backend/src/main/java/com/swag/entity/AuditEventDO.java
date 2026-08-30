package com.swag.entity;

import lombok.Data;

import java.time.OffsetDateTime;
import java.util.UUID;

/**
 * 审计事件数据对象。
 * <p>
 * 一条记录表示请求执行过程中已经发生的一项事实，例如收到用户请求、启动 Agent、
 * 调用工具、请求用户确认或执行完成。审计事件应采用追加写入方式保存，不应覆盖历史事件。
 */
@Data
public class AuditEventDO {
    /** 当前审计事件的唯一标识。 */
    private UUID eventId;

    /** 一次用户请求完整审计链的唯一标识，用于串联该请求产生的所有事件。 */
    private UUID auditId;

    /** 业务请求唯一标识，用于幂等控制和定位重复请求。 */
    private String requestId;

    /** 事件生产方生成的唯一标识，用于消息重试时防止重复入库。 */
    private String sourceEventId;

    /** Zipkin Trace 标识，用于关联并跳转到对应的分布式调用链。 */
    private String traceId;

    /** 当前事件对应的 Zipkin Span 标识。 */
    private String spanId;

    /** 当前 Span 的父级 Span 标识，用于还原 Zipkin 调用层级。 */
    private String parentSpanId;

    /** 直接触发当前事件的父审计事件标识，用于还原审计事件因果关系。 */
    private UUID parentEventId;

    /** 事件所属租户标识，用于多租户数据隔离。 */
    private String tenantId;

    /** 用户会话标识，用于关联同一会话中的多次请求。 */
    private String sessionId;

    /** 操作者类型，例如 USER、AGENT、SYSTEM、SERVICE 或 ADMIN。 */
    private String actorType;

    /** 操作者唯一标识，例如用户 ID、Agent ID 或服务账号 ID。 */
    private String actorId;

    /** 操作者展示名称，便于审计页面直接显示。 */
    private String actorDisplayName;

    /** 事件类型，例如 REQUEST_RECEIVED、TOOL_CALL_STARTED 或 CONFIRMATION_APPROVED。 */
    private String eventType;

    /** 当前操作的执行状态，例如 STARTED、SUCCEEDED、FAILED、DENIED 或 CANCELLED。 */
    private String executionStatus;

    /** 执行当前事件的 Agent 名称。 */
    private String agentName;

    /** 执行当前事件的 Agent 版本，用于定位不同版本产生的行为差异。 */
    private String agentVersion;

    /** 当前事件涉及的模型名称。 */
    private String modelName;

    /** 被调用工具的名称，非工具调用事件可以为空。 */
    private String toolName;

    /** 单次工具调用的唯一标识，用于匹配工具输入、输出、确认和重试事件。 */
    private String toolCallId;

    /** 用户确认流程的唯一标识，用于关联确认请求及其批准、拒绝或过期事件。 */
    private UUID confirmationId;

    /** 待确认操作的规范化内容摘要，用于保证用户确认内容与最终执行内容一致。 */
    private String actionDigest;

    /** 工具或模型输入原文的存储引用，敏感或大体积内容不直接写入事件表。 */
    private String inputRef;

    /** 输入原文的内容摘要，用于完整性校验和确认输入是否被修改。 */
    private String inputDigest;

    /** 工具或模型输出原文的存储引用。 */
    private String outputRef;

    /** 输出原文的内容摘要，用于完整性校验。 */
    private String outputDigest;

    /** 事件特有的扩展数据，内容为 JSON 字符串。 */
    private String eventData;

    /** 机器可识别的错误编码，执行成功时为空。 */
    private String errorCode;

    /** 供排查问题使用的错误描述，写入前应移除敏感信息。 */
    private String errorMessage;

    /** 事件在业务系统中实际发生的时间。 */
    private OffsetDateTime occurredAt;

    /** 审计系统接收并记录该事件的时间，用于判断日志写入延迟。 */
    private OffsetDateTime recordedAt;

    /** 审计事件结构版本，用于兼容不同版本的事件数据。 */
    private Integer schemaVersion;

    /** 同一审计链中前一事件的完整性哈希。 */
    private String previousHash;

    /** 当前事件内容与 previousHash 共同计算得到的完整性哈希。 */
    private String eventHash;
}

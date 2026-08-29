package com.swag.entity;

import lombok.Data;

import java.time.OffsetDateTime;
import java.util.UUID;

/**
 * 工具执行确认数据对象。
 * <p>
 * 保存待确认动作的当前状态；批准、拒绝和消费的历史事实仍以 audit_event 为准。
 */
@Data
public class AuditConfirmationDO {

    /** 确认流程唯一标识。 */
    private UUID confirmationId;

    /** 确认流程所属审计链标识。 */
    private UUID auditId;

    /** 模型产生的工具调用标识。 */
    private String toolCallId;

    /** 确认所属租户。 */
    private String tenantId;

    /** 必须作出确认的用户标识。 */
    private String actorId;

    /** 待执行工具名称。 */
    private String toolName;

    /** 经过字段排序后的规范化工具参数。 */
    private String canonicalInput;

    /** 工具名称与规范化参数共同计算出的动作摘要。 */
    private String actionDigest;

    /** 当前状态：PENDING、APPROVED、DENIED、EXPIRED 或 CONSUMED。 */
    private String status;

    /** 用户批准或拒绝时填写的原因。 */
    private String decisionReason;

    /** 发起确认的时间。 */
    private OffsetDateTime requestedAt;

    /** 用户作出决定的时间。 */
    private OffsetDateTime decidedAt;

    /** 确认失效时间。 */
    private OffsetDateTime expiresAt;

    /** 确认被实际工具调用消费的时间。 */
    private OffsetDateTime consumedAt;
}

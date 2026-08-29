package com.swag.entity;

import lombok.Data;

import java.time.OffsetDateTime;
import java.util.UUID;

/**
 * 审计载荷数据对象。
 * <p>
 * 用于保存审计事件涉及的大体积或敏感输入输出的存储信息。原始内容应加密存放在独立存储中，
 * 本对象仅记录访问引用、内容摘要、脱敏版本和生命周期信息。
 */
@Data
public class AuditPayloadDO {
    /** 审计载荷的唯一标识。 */
    private UUID payloadId;

    /** 载荷所属请求审计链的唯一标识。 */
    private UUID auditId;

    /** 载荷类型，例如 USER_INPUT、TOOL_INPUT、TOOL_OUTPUT 或 MODEL_OUTPUT。 */
    private String payloadType;

    /** 原始载荷在对象存储或其他安全存储中的访问地址。 */
    private String storageUri;

    /** 原始载荷的内容摘要，用于完整性校验和内容去重。 */
    private String contentDigest;

    /** 载荷媒体类型，例如 application/json、text/plain 或 application/pdf。 */
    private String mediaType;

    /** 原始载荷大小，单位为字节。 */
    private Long sizeBytes;

    /** 加密该载荷所使用的密钥标识，不保存密钥本身。 */
    private String encryptionKeyId;

    /** 写入载荷前所采用的脱敏规则版本。 */
    private String redactionVersion;

    /** 载荷记录创建时间。 */
    private OffsetDateTime createdAt;

    /** 载荷到期时间，到期后按照数据保留策略归档或删除。 */
    private OffsetDateTime expiresAt;
}

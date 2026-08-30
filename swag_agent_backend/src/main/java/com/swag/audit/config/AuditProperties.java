package com.swag.audit.config;

import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;

import java.time.Duration;
import java.util.LinkedHashSet;
import java.util.Set;

/**
 * 审计模块配置。
 */
@Data
@ConfigurationProperties(prefix = "audit")
public class AuditProperties {

    /** Zipkin Web UI 基础地址。 */
    private String zipkinUiBaseUrl = "http://localhost:9411";

    /** 工具确认请求的有效期。 */
    private Duration confirmationTtl = Duration.ofMinutes(10);

    /** 执行前必须获得用户确认的工具名称集合。 */
    private Set<String> confirmationRequiredTools = new LinkedHashSet<>();

    /** 是否将工具原始输入输出写入 event_data；生产环境应保持关闭。 */
    private boolean includeToolContent;
}

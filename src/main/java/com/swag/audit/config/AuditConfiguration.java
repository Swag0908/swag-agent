package com.swag.audit.config;

import org.springframework.boot.context.properties.EnableConfigurationProperties;
import org.springframework.context.annotation.Configuration;

/**
 * 审计模块配置入口。
 */
@Configuration
@EnableConfigurationProperties(AuditProperties.class)
public class AuditConfiguration {
}

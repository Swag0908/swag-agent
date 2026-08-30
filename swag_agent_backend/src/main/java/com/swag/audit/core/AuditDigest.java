package com.swag.audit.core;

import org.springframework.stereotype.Component;
import tools.jackson.databind.ObjectMapper;
import tools.jackson.databind.SerializationFeature;
import tools.jackson.databind.json.JsonMapper;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.HexFormat;

/**
 * 统一计算审计内容摘要和确认动作摘要。
 */
@Component
public class AuditDigest {

    private final ObjectMapper canonicalJsonMapper = JsonMapper.builder()
            .enable(SerializationFeature.ORDER_MAP_ENTRIES_BY_KEYS)
            .build();

    /**
     * 计算原始内容的 SHA-256。
     */
    public String sha256(String content) {
        try {
            MessageDigest digest = MessageDigest.getInstance("SHA-256");
            byte[] bytes = digest.digest(nullSafe(content).getBytes(StandardCharsets.UTF_8));
            return HexFormat.of().formatHex(bytes);
        }
        catch (NoSuchAlgorithmException exception) {
            throw new IllegalStateException("JVM does not provide SHA-256", exception);
        }
    }

    /**
     * 对 JSON 工具参数进行规范化，保证对象字段顺序不同不会改变确认摘要。
     * 非 JSON 输入保持原文。
     */
    public String canonicalizeJson(String input) {
        if (input == null || input.isBlank()) {
            return "";
        }

        try {
            Object parsed = canonicalJsonMapper.readValue(input, Object.class);
            return canonicalJsonMapper.writeValueAsString(parsed);
        }
        catch (Exception ignored) {
            return input;
        }
    }

    /**
     * 将工具名称和确切参数绑定为用户确认的动作摘要。
     */
    public String actionDigest(String toolName, String input) {
        return sha256(nullSafe(toolName) + "\n" + canonicalizeJson(input));
    }

    private String nullSafe(String value) {
        return value == null ? "" : value;
    }
}

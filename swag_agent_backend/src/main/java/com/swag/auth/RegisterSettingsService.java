package com.swag.auth;

import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;

import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.SecureRandom;
import java.time.LocalDateTime;
import java.time.ZoneId;
import java.util.Locale;

/**
 * 注册闸门：注册码生成 / 校验 / 换新，以及「新用户注册」总开关。
 * <p>
 * 注册码保存在单行表 {@code app_register_setting}（id=1），仅在管理员端可见；
 * 公开注册接口只做「是否匹配」校验，绝不返回注册码本身。
 */
@Service
public class RegisterSettingsService {

    /** 生成注册码时排除易混淆字符（0/O、1/I）。 */
    private static final String ALPHABET = "23456789ABCDEFGHJKMNPQRSTUVWXYZ";

    private static final int CODE_GROUPS = 3;
    private static final int CODE_GROUP_LENGTH = 4;

    private static final SecureRandom RANDOM = new SecureRandom();
    private final RegisterSettingsRepository repository;

    public RegisterSettingsService(RegisterSettingsRepository repository) {
        this.repository = repository;
    }

    /** 启动时确保设置行存在（无则自动生成初始注册码、默认开放注册）。 */
    public void ensureInitialized() {
        repository.createTableIfMissing();
        if (repository.find().isEmpty()) {
            repository.insertDefault(generateCode());
        }
    }

    public record Settings(String registerCode, boolean registrationEnabled, Long updatedAtMs) {
    }

    public Settings current() {
        RegisterSettingsRepository.SettingsRow row = requireRow();
        return new Settings(row.registerCode(), row.registrationEnabled(), toEpochMs(row.updatedAt()));
    }

    /**
     * 注册前闸门：总开关关闭 → 403；注册码不匹配 → 400。
     * 注意：这里只允许公开接口做真假判断，任何分支都不泄露正确注册码。
     */
    public void assertCanRegister(String registerCode) {
        RegisterSettingsRepository.SettingsRow row = requireRow();
        if (!row.registrationEnabled()) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, "注册功能当前已关闭，请联系管理员");
        }
        if (!matches(row.registerCode(), registerCode)) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "注册码不正确，请向管理员获取");
        }
    }

    /** 换新注册码（旧码立即失效）。 */
    public Settings regenerate(Long adminId) {
        repository.update(generateCode(), requireRow().registrationEnabled(), adminId);
        return current();
    }

    /** 更新开关和/或自定义注册码；传 null 表示保持原值。 */
    public Settings update(Boolean registrationEnabled, String registerCode, Long adminId) {
        RegisterSettingsRepository.SettingsRow row = requireRow();
        boolean enabled = registrationEnabled == null ? row.registrationEnabled() : registrationEnabled;
        String code = normalizeCustom(registerCode);
        if (code == null) {
            code = row.registerCode();
        }
        repository.update(code, enabled, adminId);
        return current();
    }

    private static String normalizeCustom(String registerCode) {
        if (registerCode == null || registerCode.isBlank()) {
            return null;
        }
        String code = registerCode.trim().toUpperCase(Locale.ROOT);
        if (code.length() < 6 || code.length() > 40) {
            throw new ResponseStatusException(
                    HttpStatus.BAD_REQUEST, "注册码长度需在 6-40 位之间");
        }
        return code;
    }

    private RegisterSettingsRepository.SettingsRow requireRow() {
        return repository.find().orElseThrow(() -> new IllegalStateException(
                "注册设置未初始化，请先执行 AuthSchemaInitializer"));
    }

    private static String generateCode() {
        StringBuilder code = new StringBuilder();
        for (int group = 0; group < CODE_GROUPS; group++) {
            if (group > 0) {
                code.append('-');
            }
            for (int i = 0; i < CODE_GROUP_LENGTH; i++) {
                code.append(ALPHABET.charAt(RANDOM.nextInt(ALPHABET.length())));
            }
        }
        return code.toString();
    }

    /** 常量时间比较，避免通过耗时差异探测注册码。 */
    private static boolean matches(String stored, String provided) {
        if (stored == null || provided == null) {
            return false;
        }
        byte[] expected = stored.getBytes(StandardCharsets.UTF_8);
        byte[] actual = provided.trim().toUpperCase(Locale.ROOT).getBytes(StandardCharsets.UTF_8);
        return MessageDigest.isEqual(expected, actual);
    }

    private static long toEpochMs(LocalDateTime time) {
        if (time == null) {
            return 0;
        }
        return time.atZone(ZoneId.systemDefault()).toInstant().toEpochMilli();
    }
}

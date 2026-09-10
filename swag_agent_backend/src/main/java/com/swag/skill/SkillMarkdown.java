package com.swag.skill;

import java.util.LinkedHashMap;
import java.util.Locale;
import java.util.Map;
import java.util.regex.Pattern;

/**
 * SKILL.md 解析器：YAML frontmatter（name/description）+ Markdown 正文。
 * <p>
 * 只解析技能必需的几个标量字段，不引入 YAML 依赖；frontmatter 写法遵循业界 agent skill 规范：
 * <pre>
 * ---
 * name: webapp-testing
 * description: 用 Playwright 测试本地 Web 应用时使用
 * ---
 * 正文……
 * </pre>
 * 解析失败（缺 description、技能名不合规、frontmatter 未闭合等）由调用方跳过并告警，
 * 与主流 agent 运行时（缺 description 即不加载）保持一致。
 */
final class SkillMarkdown {

    /** 技能名规范：kebab-case（小写字母/数字，单词之间单个连字符）。 */
    private static final Pattern VALID_NAME = Pattern.compile("[a-z0-9]+(?:-[a-z0-9]+)*");

    private SkillMarkdown() {
    }

    /** 解析成功的结果。 */
    record Parsed(String name, String description, String body) {
    }

    /** 解析结果；{@code ok()} 为 false 时 {@code error} 说明被跳过的原因。 */
    record Result(Parsed parsed, String error) {

        static Result ok(Parsed parsed) {
            return new Result(parsed, null);
        }

        static Result invalid(String error) {
            return new Result(null, error);
        }

        boolean ok() {
            return parsed != null;
        }
    }

    /**
     * 解析一份 SKILL.md 内容。
     *
     * @param folderName 技能所在目录名，frontmatter 未写 name 时作为兜底
     * @param raw        文件原文
     */
    static Result parse(String folderName, String raw) {
        if (raw == null || raw.isBlank()) {
            return Result.invalid("文件为空");
        }
        String text = raw.replace("\r\n", "\n").replace("\r", "\n").stripLeading();
        if (text.startsWith("\uFEFF")) {
            text = text.substring(1).stripLeading();
        }
        if (!text.startsWith("---")) {
            return Result.invalid("缺少 YAML frontmatter（文件应以 --- 开头）");
        }
        int firstLineEnd = text.indexOf('\n');
        if (firstLineEnd < 0) {
            return Result.invalid("frontmatter 未闭合");
        }

        int fenceStart = -1;
        int fenceLineEnd = -1;
        int cursor = firstLineEnd + 1;
        while (cursor <= text.length()) {
            int lineEnd = text.indexOf('\n', cursor);
            String line = lineEnd < 0 ? text.substring(cursor) : text.substring(cursor, lineEnd);
            if ("---".equals(line.strip())) {
                fenceStart = cursor;
                fenceLineEnd = lineEnd < 0 ? text.length() : lineEnd;
                break;
            }
            if (lineEnd < 0) {
                break;
            }
            cursor = lineEnd + 1;
        }
        if (fenceStart < 0) {
            return Result.invalid("frontmatter 未闭合（缺少结束的 ---）");
        }

        Map<String, String> fields = parseFields(text.substring(firstLineEnd + 1, fenceStart));
        String body = text.substring(fenceLineEnd).strip();

        String description = fields.getOrDefault("description", "").strip();
        if (description.isEmpty()) {
            return Result.invalid("frontmatter 缺少 description");
        }
        String name = fields.getOrDefault("name", "").strip();
        if (name.isEmpty()) {
            name = folderName == null ? "" : folderName.strip();
        }
        if (!VALID_NAME.matcher(name).matches()) {
            return Result.invalid("技能名不是 kebab-case：" + name);
        }
        return Result.ok(new Parsed(name, description, body));
    }

    /** 极简 frontmatter 字段解析：只认单行 {@code key: value}，忽略注释与空行。 */
    private static Map<String, String> parseFields(String frontmatter) {
        Map<String, String> fields = new LinkedHashMap<>();
        for (String line : frontmatter.split("\n")) {
            String trimmed = line.strip();
            if (trimmed.isEmpty() || trimmed.startsWith("#")) {
                continue;
            }
            int colon = trimmed.indexOf(':');
            if (colon <= 0) {
                continue;
            }
            String key = trimmed.substring(0, colon).strip().toLowerCase(Locale.ROOT);
            String value = trimmed.substring(colon + 1).strip();
            boolean quoted = value.length() >= 2
                    && ((value.startsWith("\"") && value.endsWith("\""))
                    || (value.startsWith("'") && value.endsWith("'")));
            if (quoted) {
                value = value.substring(1, value.length() - 1).strip();
            }
            fields.putIfAbsent(key, value);
        }
        return fields;
    }
}

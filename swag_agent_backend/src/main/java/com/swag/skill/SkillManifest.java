package com.swag.skill;

/**
 * 一个已发现的技能（Skill）的清单信息。
 *
 * @param name        技能名（kebab-case），注册表内的唯一键
 * @param description 何时该用这个技能的一句话说明（来自 frontmatter）
 * @param body        SKILL.md 的 Markdown 正文，注入 system prompt 的内容
 * @param external    true = 外部目录（运行时安装，可删）；false = classpath 内置（只读）
 * @param filePath    来源文件路径，便于管理端排查
 */
public record SkillManifest(
        String name,
        String description,
        String body,
        boolean external,
        String filePath) {

    /** 来源标识：builtin（随包发布）/ external（运行时安装）。 */
    public String source() {
        return external ? "external" : "builtin";
    }
}

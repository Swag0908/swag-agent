package com.swag.skill;

import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.stereotype.Component;

/**
 * Skill（技能包）模块配置。
 * <p>
 * 一个技能 = 一个含 {@code SKILL.md} 的目录（frontmatter 提供 name/description，正文是给模型的
 * 领域指南）。技能分两类来源：
 * <ul>
 *     <li><b>内置</b>：{@code classpath:skills/<name>/SKILL.md}，随 jar 发布、团队共享；</li>
 *     <li><b>外部</b>：{@code <external-root>/<name>/SKILL.md}，运行时安装/热插拔，同名覆盖内置。</li>
 * </ul>
 * 技能正文只作为提示词注入，不会被执行；需要"真正能执行的外部能力"应走工具（@Tool 或 MCP server）。
 */
@Data
@Component
@ConfigurationProperties(prefix = "app.skills")
public class SkillProperties {

    /** 运行时安装的技能根目录（可写）。默认落在后端工作目录下的 ./skills-data，生产可设为 /opt/... */
    private String externalRoot = "./skills-data";

    /** 是否把启用中的技能正文注入 system prompt。关闭后管理端仍可查看/启停技能。 */
    private boolean autoInject = true;

    /** 单个技能正文注入上限（字符），超出截断，避免外部技能挤爆上下文。 */
    private int maxBodyChars = 20000;

    /** 是否允许管理端从 Git 仓库安装技能（POST /auth/admin/skills/install）。 */
    private boolean installEnabled = true;

    /** 安装技能时 git clone 的超时时间（秒）。公开 Skill 仓库通常很小，超时应尽快反馈网络故障。 */
    private int installTimeoutSeconds = 60;
}

-- 技能包启停状态：一行一个「被显式设置过」的技能，缺行 = 默认启用。
-- 技能正文本身来自磁盘（内置 classpath 或外部 skills-data 目录），这里只持久化启停，
-- 因此换机器/重启后端后，管理端设置过的启停状态依然生效。
CREATE TABLE IF NOT EXISTS skill_state (
    skill_name VARCHAR(128) NOT NULL COMMENT '技能名（kebab-case，与 SKILL.md frontmatter 的 name 一致）',
    enabled    TINYINT(1)   NOT NULL DEFAULT 1 COMMENT '1=启用，0=停用',
    updated_at DATETIME(6)  NOT NULL COMMENT '最后修改时间',
    PRIMARY KEY (skill_name)
) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4 COMMENT = '技能包启停状态';

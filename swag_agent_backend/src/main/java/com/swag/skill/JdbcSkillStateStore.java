package com.swag.skill;

import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Repository;

import java.sql.Timestamp;
import java.time.LocalDateTime;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Set;

/**
 * 技能启停状态的 JDBC 实现，表结构见 Flyway 迁移 {@code V2__skill_state.sql}。
 */
@Repository
public class JdbcSkillStateStore implements SkillStateStore {

    private final NamedParameterJdbcTemplate jdbc;

    public JdbcSkillStateStore(NamedParameterJdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    @Override
    public Set<String> disabledSkills() {
        List<String> names = jdbc.queryForList(
                "SELECT skill_name FROM skill_state WHERE enabled = 0",
                new MapSqlParameterSource(),
                String.class);
        return new LinkedHashSet<>(names);
    }

    @Override
    public void setEnabled(String name, boolean enabled) {
        jdbc.update("""
                INSERT INTO skill_state (skill_name, enabled, updated_at)
                VALUES (:name, :enabled, :updatedAt)
                ON DUPLICATE KEY UPDATE enabled = VALUES(enabled), updated_at = VALUES(updated_at)
                """,
                new MapSqlParameterSource()
                        .addValue("name", name)
                        .addValue("enabled", enabled ? 1 : 0)
                        .addValue("updatedAt", Timestamp.valueOf(LocalDateTime.now())));
    }

    @Override
    public void remove(String name) {
        jdbc.update("DELETE FROM skill_state WHERE skill_name = :name",
                new MapSqlParameterSource("name", name));
    }

    @Override
    public int removeMissing(Set<String> existingNames) {
        if (existingNames == null || existingNames.isEmpty()) {
            return 0;
        }
        return jdbc.update("DELETE FROM skill_state WHERE skill_name NOT IN (:names)",
                new MapSqlParameterSource("names", existingNames));
    }
}

package com.swag.auth;

import org.springframework.jdbc.core.RowMapper;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Repository;

import java.sql.Timestamp;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Optional;

/**
 * 注册设置（注册码 + 注册开关）的单行 JDBC 访问，行 id 固定为 1。
 */
@Repository
public class RegisterSettingsRepository {

    private static final long SETTINGS_ID = 1L;

    public record SettingsRow(String registerCode, boolean registrationEnabled,
                              LocalDateTime updatedAt, Long updatedBy) {
    }

    private static final RowMapper<SettingsRow> ROW_MAPPER = (rs, i) -> {
        Timestamp updatedAt = rs.getTimestamp("updated_at");
        long updatedBy = rs.getLong("updated_by");
        return new SettingsRow(
                rs.getString("register_code"),
                rs.getBoolean("registration_enabled"),
                updatedAt == null ? null : updatedAt.toLocalDateTime(),
                rs.wasNull() ? null : updatedBy);
    };

    private final NamedParameterJdbcTemplate jdbc;

    public RegisterSettingsRepository(NamedParameterJdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    public void createTableIfMissing() {
        jdbc.getJdbcOperations().execute("""
                CREATE TABLE IF NOT EXISTS app_register_setting (
                    id                   TINYINT       NOT NULL,
                    register_code        VARCHAR(64)   NOT NULL,
                    registration_enabled TINYINT(1)    NOT NULL DEFAULT 1,
                    updated_by           BIGINT        NULL,
                    updated_at           DATETIME(6)   NOT NULL,
                    PRIMARY KEY (id)
                ) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4
                """);
    }

    public Optional<SettingsRow> find() {
        List<SettingsRow> list = jdbc.query(
                "SELECT register_code, registration_enabled, updated_at, updated_by"
                        + " FROM app_register_setting WHERE id = :id",
                new MapSqlParameterSource("id", SETTINGS_ID),
                ROW_MAPPER);
        return list.stream().findFirst();
    }

    public void insertDefault(String registerCode) {
        jdbc.update("""
                        INSERT INTO app_register_setting (id, register_code, registration_enabled, updated_at)
                        VALUES (:id, :code, 1, :now)
                        """,
                new MapSqlParameterSource()
                        .addValue("id", SETTINGS_ID)
                        .addValue("code", registerCode)
                        .addValue("now", Timestamp.valueOf(LocalDateTime.now())));
    }

    public void update(String registerCode, boolean registrationEnabled, Long updatedBy) {
        jdbc.update("""
                        UPDATE app_register_setting
                        SET register_code = :code, registration_enabled = :enabled,
                            updated_by = :updatedBy, updated_at = :now
                        WHERE id = :id
                        """,
                new MapSqlParameterSource()
                        .addValue("code", registerCode)
                        .addValue("enabled", registrationEnabled ? 1 : 0)
                        .addValue("updatedBy", updatedBy)
                        .addValue("now", Timestamp.valueOf(LocalDateTime.now()))
                        .addValue("id", SETTINGS_ID));
    }
}

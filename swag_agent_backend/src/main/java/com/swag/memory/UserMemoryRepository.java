package com.swag.memory;

import jakarta.annotation.PostConstruct;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.jdbc.support.GeneratedKeyHolder;
import org.springframework.jdbc.support.KeyHolder;
import org.springframework.stereotype.Repository;

import java.sql.Timestamp;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Optional;

/**
 * 用户记忆本体（MySQL）：记忆文本 + 用户级开关。
 * 向量化副本单独落在 pgvector（见 UserMemoryVectorRepository）。
 */
@Repository
public class UserMemoryRepository {

    private static final Logger log = LoggerFactory.getLogger(UserMemoryRepository.class);

    private static final String COLUMNS = "id, user_id, content, created_at, updated_at";

    private final NamedParameterJdbcTemplate jdbc;

    public UserMemoryRepository(NamedParameterJdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    @PostConstruct
    public void ensureSchema() {
        jdbc.getJdbcOperations().execute("""
                CREATE TABLE IF NOT EXISTS chat_user_memory (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    content TEXT NOT NULL,
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL,
                    KEY idx_user_memory_user (user_id, updated_at)
                ) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4
                """);
        jdbc.getJdbcOperations().execute("""
                CREATE TABLE IF NOT EXISTS chat_user_memory_setting (
                    user_id BIGINT PRIMARY KEY,
                    enabled TINYINT(1) NOT NULL DEFAULT 1,
                    updated_at DATETIME NOT NULL
                ) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4
                """);
        log.info("chat_user_memory / chat_user_memory_setting 表结构已就绪");
    }

    private static final RowMapper<UserMemoryDO> MAPPER = (rs, i) -> {
        UserMemoryDO memory = new UserMemoryDO();
        memory.setId(rs.getLong("id"));
        memory.setUserId(rs.getLong("user_id"));
        memory.setContent(rs.getString("content"));
        memory.setCreatedAt(rs.getTimestamp("created_at").toLocalDateTime());
        memory.setUpdatedAt(rs.getTimestamp("updated_at").toLocalDateTime());
        return memory;
    };

    public UserMemoryDO insert(Long userId, String content, LocalDateTime now) {
        KeyHolder keyHolder = new GeneratedKeyHolder();
        jdbc.update("""
                        INSERT INTO chat_user_memory (user_id, content, created_at, updated_at)
                        VALUES (:userId, :content, :now, :now)
                        """,
                new MapSqlParameterSource()
                        .addValue("userId", userId)
                        .addValue("content", content)
                        .addValue("now", Timestamp.valueOf(now)),
                keyHolder,
                new String[]{"id"});
        UserMemoryDO memory = new UserMemoryDO();
        memory.setId(keyHolder.getKey().longValue());
        memory.setUserId(userId);
        memory.setContent(content);
        memory.setCreatedAt(now);
        memory.setUpdatedAt(now);
        return memory;
    }

    public List<UserMemoryDO> list(Long userId) {
        return jdbc.query("SELECT " + COLUMNS + " FROM chat_user_memory"
                        + " WHERE user_id = :userId ORDER BY updated_at DESC, id DESC",
                new MapSqlParameterSource("userId", userId),
                MAPPER);
    }

    public Optional<UserMemoryDO> findById(Long id, Long userId) {
        List<UserMemoryDO> rows = jdbc.query("SELECT " + COLUMNS + " FROM chat_user_memory"
                        + " WHERE id = :id AND user_id = :userId",
                new MapSqlParameterSource().addValue("id", id).addValue("userId", userId),
                MAPPER);
        return rows.stream().findFirst();
    }

    public boolean delete(Long id, Long userId) {
        int affected = jdbc.update("DELETE FROM chat_user_memory WHERE id = :id AND user_id = :userId",
                new MapSqlParameterSource().addValue("id", id).addValue("userId", userId));
        return affected > 0;
    }

    /** 开关缺省视为开启；新用户尚无设置行时返回 true（不能 queryForObject，空结果会抛异常）。 */
    public boolean isEnabled(Long userId) {
        List<Integer> rows = jdbc.query(
                "SELECT enabled FROM chat_user_memory_setting WHERE user_id = :userId",
                new MapSqlParameterSource("userId", userId),
                (rs, rowNum) -> rs.getInt("enabled"));
        return rows.isEmpty() || rows.get(0) == 1;
    }

    public void setEnabled(Long userId, boolean enabled, LocalDateTime now) {
        jdbc.update("""
                        INSERT INTO chat_user_memory_setting (user_id, enabled, updated_at)
                        VALUES (:userId, :enabled, :now)
                        ON DUPLICATE KEY UPDATE enabled = :enabled, updated_at = :now
                        """,
                new MapSqlParameterSource()
                        .addValue("userId", userId)
                        .addValue("enabled", enabled ? 1 : 0)
                        .addValue("now", Timestamp.valueOf(now)));
    }
}

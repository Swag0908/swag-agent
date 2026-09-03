package com.swag.chat;

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
 * 历史会话与消息的 JDBC 访问（MySQL）。
 * <p>
 * 建表不依赖 Flyway 迁移文件（db/migration 已被有意清空），改为启动时幂等建表，
 * 与 Spring AI 记忆 starter 自动建表的方式保持一致。
 */
@Repository
public class ChatHistoryRepository {

    private static final Logger log = LoggerFactory.getLogger(ChatHistoryRepository.class);

    private static final String CONVERSATION_COLUMNS = "id, user_id, title, created_at, updated_at";
    private static final String MESSAGE_COLUMNS = "id, conversation_id, user_id, role, content, created_at";

    private final NamedParameterJdbcTemplate jdbc;

    public ChatHistoryRepository(NamedParameterJdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    @PostConstruct
    public void ensureSchema() {
        jdbc.getJdbcOperations().execute("""
                CREATE TABLE IF NOT EXISTS chat_conversation (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    user_id BIGINT NOT NULL,
                    title VARCHAR(120) NOT NULL DEFAULT '',
                    created_at DATETIME NOT NULL,
                    updated_at DATETIME NOT NULL,
                    KEY idx_chat_conv_user (user_id, updated_at)
                ) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4
                """);
        jdbc.getJdbcOperations().execute("""
                CREATE TABLE IF NOT EXISTS chat_message (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    conversation_id BIGINT NOT NULL,
                    user_id BIGINT NOT NULL,
                    role VARCHAR(16) NOT NULL,
                    content MEDIUMTEXT NOT NULL,
                    created_at DATETIME NOT NULL,
                    KEY idx_chat_msg_conv (conversation_id, id)
                ) ENGINE = InnoDB DEFAULT CHARSET = utf8mb4
                """);
        log.info("chat_conversation / chat_message 表结构已就绪");
    }

    private static final RowMapper<ChatConversationDO> CONVERSATION_MAPPER = (rs, i) -> {
        ChatConversationDO conv = new ChatConversationDO();
        conv.setId(rs.getLong("id"));
        conv.setUserId(rs.getLong("user_id"));
        conv.setTitle(rs.getString("title"));
        conv.setCreatedAt(rs.getTimestamp("created_at").toLocalDateTime());
        conv.setUpdatedAt(rs.getTimestamp("updated_at").toLocalDateTime());
        return conv;
    };

    private static final RowMapper<ChatMessageDO> MESSAGE_MAPPER = (rs, i) -> {
        ChatMessageDO msg = new ChatMessageDO();
        msg.setId(rs.getLong("id"));
        msg.setConversationId(rs.getLong("conversation_id"));
        msg.setUserId(rs.getLong("user_id"));
        msg.setRole(rs.getString("role"));
        msg.setContent(rs.getString("content"));
        msg.setCreatedAt(rs.getTimestamp("created_at").toLocalDateTime());
        return msg;
    };

    public ChatConversationDO insertConversation(Long userId, String title, LocalDateTime now) {
        KeyHolder keyHolder = new GeneratedKeyHolder();
        jdbc.update("""
                        INSERT INTO chat_conversation (user_id, title, created_at, updated_at)
                        VALUES (:userId, :title, :now, :now)
                        """,
                new MapSqlParameterSource()
                        .addValue("userId", userId)
                        .addValue("title", title == null ? "" : title)
                        .addValue("now", Timestamp.valueOf(now)),
                keyHolder,
                new String[]{"id"});
        ChatConversationDO conv = new ChatConversationDO();
        conv.setId(keyHolder.getKey().longValue());
        conv.setUserId(userId);
        conv.setTitle(title == null ? "" : title);
        conv.setCreatedAt(now);
        conv.setUpdatedAt(now);
        return conv;
    }

    public Optional<ChatConversationDO> findConversation(Long id, Long userId) {
        List<ChatConversationDO> rows = jdbc.query(
                "SELECT " + CONVERSATION_COLUMNS + " FROM chat_conversation"
                        + " WHERE id = :id AND user_id = :userId",
                new MapSqlParameterSource().addValue("id", id).addValue("userId", userId),
                CONVERSATION_MAPPER);
        return rows.stream().findFirst();
    }

    public List<ChatConversationDO> listConversations(Long userId) {
        return jdbc.query("SELECT " + CONVERSATION_COLUMNS + " FROM chat_conversation"
                        + " WHERE user_id = :userId ORDER BY updated_at DESC, id DESC",
                new MapSqlParameterSource("userId", userId),
                CONVERSATION_MAPPER);
    }

    /** 标题为空时自动用首句提问填充。 */
    public void updateTitleIfEmpty(Long id, String title, LocalDateTime now) {
        jdbc.update("""
                        UPDATE chat_conversation
                        SET title = :title, updated_at = :now
                        WHERE id = :id AND (title IS NULL OR title = '')
                        """,
                new MapSqlParameterSource()
                        .addValue("id", id)
                        .addValue("title", title)
                        .addValue("now", Timestamp.valueOf(now)));
    }

    public void touchConversation(Long id, LocalDateTime now) {
        jdbc.update("UPDATE chat_conversation SET updated_at = :now WHERE id = :id",
                new MapSqlParameterSource()
                        .addValue("id", id)
                        .addValue("now", Timestamp.valueOf(now)));
    }

    public ChatMessageDO insertMessage(Long conversationId, Long userId, String role,
                                       String content, LocalDateTime now) {
        KeyHolder keyHolder = new GeneratedKeyHolder();
        jdbc.update("""
                        INSERT INTO chat_message (conversation_id, user_id, role, content, created_at)
                        VALUES (:conversationId, :userId, :role, :content, :now)
                        """,
                new MapSqlParameterSource()
                        .addValue("conversationId", conversationId)
                        .addValue("userId", userId)
                        .addValue("role", role)
                        .addValue("content", content)
                        .addValue("now", Timestamp.valueOf(now)),
                keyHolder,
                new String[]{"id"});
        ChatMessageDO msg = new ChatMessageDO();
        msg.setId(keyHolder.getKey().longValue());
        msg.setConversationId(conversationId);
        msg.setUserId(userId);
        msg.setRole(role);
        msg.setContent(content);
        msg.setCreatedAt(now);
        return msg;
    }

    public List<ChatMessageDO> listMessages(Long conversationId) {
        return jdbc.query("SELECT " + MESSAGE_COLUMNS + " FROM chat_message"
                        + " WHERE conversation_id = :conversationId ORDER BY id",
                new MapSqlParameterSource("conversationId", conversationId),
                MESSAGE_MAPPER);
    }
}

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
import org.springframework.transaction.annotation.Transactional;

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

    private static final String CONVERSATION_COLUMNS = "id, user_id, title, favorite, favorite_note,"
            + " favorite_order, favorited_at, created_at, updated_at";
    private static final String MESSAGE_COLUMNS = "id, conversation_id, user_id, role, content, created_at";

    /**
     * 排在最前面的收藏会话按手动排序号升序；未收藏的会话 favorite_order 为 NULL，
     * 统一落到末尾并按 updated_at 倒序，保持原有「最近活跃在前」的观感。
     */
    private static final String CONVERSATION_ORDER =
            " ORDER BY favorite DESC, COALESCE(favorite_order, 2147483647) ASC, updated_at DESC, id DESC";

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
        // 收藏会话：老库通过幂等补列升级，不需要额外的迁移文件（见类注释）
        addColumnIfMissing("chat_conversation", "favorite",
                "favorite TINYINT(1) NOT NULL DEFAULT 0");
        addColumnIfMissing("chat_conversation", "favorite_note",
                "favorite_note VARCHAR(120) NULL");
        addColumnIfMissing("chat_conversation", "favorite_order",
                "favorite_order INT NULL");
        addColumnIfMissing("chat_conversation", "favorited_at",
                "favorited_at DATETIME NULL");
        log.info("chat_conversation / chat_message 表结构已就绪");
    }

    /**
     * MySQL 8 的 {@code ADD COLUMN} 不支持 {@code IF NOT EXISTS}，
     * 因此先查 information_schema 再决定是否执行 DDL，保证重启幂等。
     */
    private void addColumnIfMissing(String table, String column, String columnDdl) {
        Integer existing = jdbc.queryForObject("""
                SELECT COUNT(*) FROM information_schema.columns
                WHERE table_schema = DATABASE() AND table_name = :table AND column_name = :column
                """,
                new MapSqlParameterSource().addValue("table", table).addValue("column", column),
                Integer.class);
        if (existing != null && existing == 0) {
            jdbc.getJdbcOperations().execute("ALTER TABLE " + table + " ADD COLUMN " + columnDdl);
            log.info("已为 {}.{} 补充列", table, column);
        }
    }

    private static final RowMapper<ChatConversationDO> CONVERSATION_MAPPER = (rs, i) -> {
        ChatConversationDO conv = new ChatConversationDO();
        conv.setId(rs.getLong("id"));
        conv.setUserId(rs.getLong("user_id"));
        conv.setTitle(rs.getString("title"));
        conv.setFavorite(rs.getBoolean("favorite"));
        conv.setFavoriteNote(rs.getString("favorite_note"));
        conv.setFavoriteOrder(rs.getObject("favorite_order", Integer.class));
        Timestamp favoritedAt = rs.getTimestamp("favorited_at");
        conv.setFavoritedAt(favoritedAt == null ? null : favoritedAt.toLocalDateTime());
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
                        + " WHERE user_id = :userId" + CONVERSATION_ORDER,
                new MapSqlParameterSource("userId", userId),
                CONVERSATION_MAPPER);
    }

    /**
     * 收藏 / 取消收藏。备注名与排序号只在收藏态下有意义，取消收藏时一并清空，
     * 避免下次重新收藏时沿用上一次的备注。
     *
     * @param favoriteOrder 收藏区内的排序号；为 null 时排在同组最后
     */
    public boolean setFavorite(Long id, Long userId, boolean favorite, String note,
                               Integer favoriteOrder, LocalDateTime now) {
        if (favorite) {
            int updated = jdbc.update("""
                            UPDATE chat_conversation
                            SET favorite = 1,
                                favorite_note = :note,
                                favorite_order = :favoriteOrder,
                                favorited_at = COALESCE(favorited_at, :now)
                            WHERE id = :id AND user_id = :userId
                            """,
                    new MapSqlParameterSource()
                            .addValue("id", id)
                            .addValue("userId", userId)
                            .addValue("note", note)
                            .addValue("favoriteOrder", favoriteOrder)
                            .addValue("now", Timestamp.valueOf(now)));
            return updated > 0;
        }
        int updated = jdbc.update("""
                        UPDATE chat_conversation
                        SET favorite = 0,
                            favorite_note = NULL,
                            favorite_order = NULL,
                            favorited_at = NULL
                        WHERE id = :id AND user_id = :userId
                        """,
                new MapSqlParameterSource().addValue("id", id).addValue("userId", userId));
        return updated > 0;
    }

    /** 收藏区内的最大排序号；没有收藏时返回 -1，便于新收藏排到末尾。 */
    public int maxFavoriteOrder(Long userId) {
        Integer max = jdbc.queryForObject("""
                        SELECT COALESCE(MAX(favorite_order), -1) FROM chat_conversation
                        WHERE user_id = :userId AND favorite = 1
                        """,
                new MapSqlParameterSource("userId", userId),
                Integer.class);
        return max == null ? -1 : max;
    }

    /** 按前端提交的顺序重排收藏区；只影响属于该用户且已收藏的会话。 */
    public void reorderFavorites(Long userId, List<Long> orderedIds) {
        if (orderedIds == null || orderedIds.isEmpty()) {
            return;
        }
        MapSqlParameterSource[] batch = new MapSqlParameterSource[orderedIds.size()];
        for (int i = 0; i < orderedIds.size(); i++) {
            batch[i] = new MapSqlParameterSource()
                    .addValue("id", orderedIds.get(i))
                    .addValue("userId", userId)
                    .addValue("favoriteOrder", i);
        }
        jdbc.batchUpdate("""
                UPDATE chat_conversation SET favorite_order = :favoriteOrder
                WHERE id = :id AND user_id = :userId AND favorite = 1
                """, batch);
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

    /** 删除当前用户的会话及其全部历史消息。 */
    @Transactional
    public boolean deleteConversation(Long id, Long userId) {
        MapSqlParameterSource params = new MapSqlParameterSource()
                .addValue("id", id)
                .addValue("userId", userId);
        int deleted = jdbc.update(
                "DELETE FROM chat_conversation WHERE id = :id AND user_id = :userId",
                params);
        if (deleted == 0) {
            return false;
        }
        jdbc.update("DELETE FROM chat_message WHERE conversation_id = :id AND user_id = :userId",
                params);
        return true;
    }

    /**
     * 删除会话内的指定消息（一问一答成对删除由上层决定）。
     * 同时命中 conversation_id 与 user_id，避免越权删除别人的消息。
     *
     * @return 实际删除的行数
     */
    @Transactional
    public int deleteMessages(Long conversationId, Long userId, List<Long> messageIds) {
        if (messageIds == null || messageIds.isEmpty()) {
            return 0;
        }
        return jdbc.update("""
                        DELETE FROM chat_message
                        WHERE conversation_id = :conversationId
                          AND user_id = :userId
                          AND id IN (:messageIds)
                        """,
                new MapSqlParameterSource()
                        .addValue("conversationId", conversationId)
                        .addValue("userId", userId)
                        .addValue("messageIds", messageIds));
    }

    /** 清空当前用户的全部会话与聊天记录，返回被清掉的会话 id（供上层回收记忆与审计）。 */
    @Transactional
    public List<Long> deleteAllConversations(Long userId) {
        List<Long> ids = jdbc.queryForList(
                "SELECT id FROM chat_conversation WHERE user_id = :userId",
                new MapSqlParameterSource("userId", userId),
                Long.class);
        if (ids.isEmpty()) {
            return ids;
        }
        MapSqlParameterSource params = new MapSqlParameterSource("userId", userId);
        jdbc.update("DELETE FROM chat_message WHERE user_id = :userId", params);
        jdbc.update("DELETE FROM chat_conversation WHERE user_id = :userId", params);
        return ids;
    }
}

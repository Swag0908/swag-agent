package com.swag.audit.core;

import jakarta.annotation.PostConstruct;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.stereotype.Repository;
import org.springframework.transaction.annotation.Transactional;

/**
 * 审计事件与聊天会话的关联、以及按会话回收审计数据。
 *
 * <p>审计表里的 {@code session_id} 存的是 HTTP Session（本项目用 token 鉴权，一直是 NULL），
 * 无法定位「这次请求属于哪个聊天会话」，因此单独补一列 {@code conversation_id}：
 * 聊天请求携带的 conversationId 会写进该列，一次请求派生出的工具调用等事件共享同一上下文，
 * 于是删除会话时可以把这条会话的审计记录一并回收。
 *
 * <p>建表/补列跟随 chat 模块的做法在启动时幂等执行（db/migration 已被有意清空），
 * 并且只在审计表确实存在时才补列，保证全新库也能正常启动。
 */
@Repository
public class AuditConversationRepository {

    private static final Logger log = LoggerFactory.getLogger(AuditConversationRepository.class);

    private static final String AUDIT_EVENT_TABLE = "audit_event";
    private static final String AUDIT_PAYLOAD_TABLE = "audit_payload";
    private static final String CONVERSATION_ID_COLUMN = "conversation_id";

    private final NamedParameterJdbcTemplate jdbc;

    public AuditConversationRepository(NamedParameterJdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    @PostConstruct
    public void ensureSchema() {
        if (!tableExists(AUDIT_EVENT_TABLE)) {
            log.warn("未找到 {} 表，跳过 conversation_id 补列（审计库未初始化？）", AUDIT_EVENT_TABLE);
            return;
        }
        addColumnIfMissing(AUDIT_EVENT_TABLE, CONVERSATION_ID_COLUMN,
                CONVERSATION_ID_COLUMN + " VARCHAR(64) NULL");
        addIndexIfMissing(AUDIT_EVENT_TABLE, "idx_audit_event_conversation",
                "(conversation_id, occurred_at)");
    }

    /**
     * 删除某会话的全部审计事件及其载荷引用。
     *
     * <p>先删 audit_payload（它按 audit_id 引用事件），再删 audit_event。
     * 审计表当前没有实现哈希链（previous_hash / event_hash 均为 NULL），
     * 因此删除行不会破坏链式校验。
     *
     * @return 删除的事件行数
     */
    @Transactional
    public int deleteByConversationId(String conversationId) {
        if (conversationId == null || conversationId.isBlank() || !tableExists(AUDIT_EVENT_TABLE)) {
            return 0;
        }
        MapSqlParameterSource params = new MapSqlParameterSource("conversationId", conversationId);
        if (tableExists(AUDIT_PAYLOAD_TABLE)) {
            jdbc.update("""
                    DELETE FROM audit_payload WHERE audit_id IN (
                        SELECT audit_id FROM audit_event WHERE conversation_id = :conversationId
                    )
                    """, params);
        }
        return jdbc.update(
                "DELETE FROM audit_event WHERE conversation_id = :conversationId", params);
    }

    private boolean tableExists(String table) {
        Integer count = jdbc.queryForObject("""
                SELECT COUNT(*) FROM information_schema.tables
                WHERE table_schema = DATABASE() AND table_name = :table
                """,
                new MapSqlParameterSource("table", table),
                Integer.class);
        return count != null && count > 0;
    }

    private void addColumnIfMissing(String table, String column, String columnDdl) {
        Integer existing = columnCount(table, column);
        if (existing != null && existing == 0) {
            jdbc.getJdbcOperations().execute("ALTER TABLE " + table + " ADD COLUMN " + columnDdl);
            log.info("已为 {}.{} 补充列", table, column);
        }
    }

    private void addIndexIfMissing(String table, String indexName, String columns) {
        Integer existing = jdbc.queryForObject("""
                SELECT COUNT(*) FROM information_schema.statistics
                WHERE table_schema = DATABASE() AND table_name = :table AND index_name = :indexName
                """,
                new MapSqlParameterSource().addValue("table", table).addValue("indexName", indexName),
                Integer.class);
        if (existing != null && existing == 0) {
            jdbc.getJdbcOperations().execute(
                    "ALTER TABLE " + table + " ADD INDEX " + indexName + " " + columns);
            log.info("已为 {} 补充索引 {}", table, indexName);
        }
    }

    private Integer columnCount(String table, String column) {
        return jdbc.queryForObject("""
                SELECT COUNT(*) FROM information_schema.columns
                WHERE table_schema = DATABASE() AND table_name = :table AND column_name = :column
                """,
                new MapSqlParameterSource().addValue("table", table).addValue("column", column),
                Integer.class);
    }
}

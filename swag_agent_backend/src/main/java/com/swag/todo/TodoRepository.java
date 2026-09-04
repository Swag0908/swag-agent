package com.swag.todo;

import org.springframework.jdbc.core.RowMapper;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.jdbc.support.GeneratedKeyHolder;
import org.springframework.jdbc.support.KeyHolder;
import org.springframework.stereotype.Repository;

import java.math.BigDecimal;
import java.sql.Date;
import java.sql.Time;
import java.sql.Timestamp;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Optional;

/**
 * 待办条目的 JDBC 访问。
 */
@Repository
public class TodoRepository {

    private static final String ITEM_COLUMNS =
            "id, user_id, title, note, due_date, due_time, status, source,"
                    + " created_at, completed_at, updated_at";

    private final NamedParameterJdbcTemplate jdbc;

    public TodoRepository(NamedParameterJdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    private static final RowMapper<TodoItemDO> ITEM_MAPPER = (rs, i) -> {
        TodoItemDO item = new TodoItemDO();
        item.setId(rs.getLong("id"));
        item.setUserId(rs.getLong("user_id"));
        item.setTitle(rs.getString("title"));
        item.setNote(rs.getString("note"));
        Date dueDate = rs.getDate("due_date");
        item.setDueDate(dueDate == null ? null : dueDate.toLocalDate());
        Time dueTime = rs.getTime("due_time");
        item.setDueTime(dueTime == null ? null : dueTime.toLocalTime());
        item.setStatus(rs.getString("status"));
        item.setSource(rs.getString("source"));
        item.setCreatedAt(rs.getTimestamp("created_at").toLocalDateTime());
        Timestamp completedAt = rs.getTimestamp("completed_at");
        item.setCompletedAt(completedAt == null ? null : completedAt.toLocalDateTime());
        item.setUpdatedAt(rs.getTimestamp("updated_at").toLocalDateTime());
        return item;
    };

    private static final RowMapper<TodoDailyStatDO> STAT_MAPPER = (rs, i) -> {
        TodoDailyStatDO stat = new TodoDailyStatDO();
        stat.setStatDate(rs.getDate("stat_date").toLocalDate());
        stat.setUserId(rs.getLong("user_id"));
        stat.setCreatedCount(rs.getInt("created_count"));
        stat.setCompletedCount(rs.getInt("completed_count"));
        stat.setPendingCount(rs.getInt("pending_count"));
        stat.setDeferredCount(rs.getInt("deferred_count"));
        stat.setCompletionRate(rs.getBigDecimal("completion_rate"));
        return stat;
    };

    public TodoItemDO insert(TodoItemDO item) {
        KeyHolder keyHolder = new GeneratedKeyHolder();
        jdbc.update("""
                        INSERT INTO todo_item
                            (user_id, title, note, due_date, due_time, status, source,
                             created_at, completed_at, updated_at)
                        VALUES
                            (:userId, :title, :note, :dueDate, :dueTime, :status, :source,
                             :createdAt, :completedAt, :updatedAt)
                        """,
                baseParams(item),
                keyHolder,
                new String[]{"id"});
        item.setId(keyHolder.getKey().longValue());
        return item;
    }

    public Optional<TodoItemDO> findById(Long id) {
        List<TodoItemDO> list = jdbc.query(
                "SELECT " + ITEM_COLUMNS + " FROM todo_item WHERE id = :id",
                new MapSqlParameterSource("id", id),
                ITEM_MAPPER);
        return list.stream().findFirst();
    }

    public List<TodoItemDO> listByDate(Long userId, LocalDate date) {
        return jdbc.query(
                "SELECT " + ITEM_COLUMNS + " FROM todo_item"
                        + " WHERE user_id = :userId AND due_date = :date"
                        + " ORDER BY (due_time IS NULL), due_time, id",
                new MapSqlParameterSource()
                        .addValue("userId", userId)
                        .addValue("date", Date.valueOf(date)),
                ITEM_MAPPER);
    }

    public List<TodoItemDO> listByDateRange(Long userId, LocalDate from, LocalDate to) {
        return jdbc.query(
                "SELECT " + ITEM_COLUMNS + " FROM todo_item"
                        + " WHERE user_id = :userId AND due_date BETWEEN :from AND :to"
                        + " ORDER BY due_date, (due_time IS NULL), due_time, id",
                new MapSqlParameterSource()
                        .addValue("userId", userId)
                        .addValue("from", Date.valueOf(from))
                        .addValue("to", Date.valueOf(to)),
                ITEM_MAPPER);
    }

    public List<TodoItemDO> listAll(Long userId) {
        return jdbc.query(
                "SELECT " + ITEM_COLUMNS + " FROM todo_item"
                        + " WHERE user_id = :userId ORDER BY due_date, id",
                new MapSqlParameterSource("userId", userId),
                ITEM_MAPPER);
    }

    public void complete(Long id, Long userId, LocalDateTime completedAt, LocalDateTime updatedAt) {
        jdbc.update("""
                        UPDATE todo_item
                        SET status = 'DONE', completed_at = :completedAt, updated_at = :updatedAt
                        WHERE id = :id AND user_id = :userId
                        """,
                new MapSqlParameterSource()
                        .addValue("id", id)
                        .addValue("userId", userId)
                        .addValue("completedAt", Timestamp.valueOf(completedAt))
                        .addValue("updatedAt", Timestamp.valueOf(updatedAt)));
    }

    public void updateDueDate(Long id, Long userId, LocalDate newDate, LocalDateTime updatedAt) {
        jdbc.update("""
                        UPDATE todo_item SET due_date = :dueDate, updated_at = :updatedAt
                        WHERE id = :id AND user_id = :userId
                        """,
                new MapSqlParameterSource()
                        .addValue("id", id)
                        .addValue("userId", userId)
                        .addValue("dueDate", Date.valueOf(newDate))
                        .addValue("updatedAt", Timestamp.valueOf(updatedAt)));
    }

    public void update(TodoItemDO item) {
        jdbc.update("""
                        UPDATE todo_item
                        SET title = :title, note = :note, due_date = :dueDate,
                            due_time = :dueTime, updated_at = :updatedAt
                        WHERE id = :id AND user_id = :userId
                        """,
                baseParams(item)
                        .addValue("id", item.getId()));
    }

    public void delete(Long id, Long userId) {
        jdbc.update("DELETE FROM todo_item WHERE id = :id AND user_id = :userId",
                new MapSqlParameterSource().addValue("id", id).addValue("userId", userId));
    }

    public void insertDeferLog(Long itemId, Long userId, LocalDate fromDate, LocalDate toDate,
                               LocalDateTime deferredAt) {
        jdbc.update("""
                        INSERT INTO todo_defer_log (item_id, user_id, from_date, to_date, deferred_at)
                        VALUES (:itemId, :userId, :fromDate, :toDate, :deferredAt)
                        """,
                new MapSqlParameterSource()
                        .addValue("itemId", itemId)
                        .addValue("userId", userId)
                        .addValue("fromDate", Date.valueOf(fromDate))
                        .addValue("toDate", Date.valueOf(toDate))
                        .addValue("deferredAt", Timestamp.valueOf(deferredAt)));
    }

    public int countCreated(Long userId, LocalDate date) {
        return count("SELECT COUNT(*) FROM todo_item"
                + " WHERE user_id = :userId AND DATE(created_at) = :date", userId, date);
    }

    public int countCompleted(Long userId, LocalDate date) {
        return count("SELECT COUNT(*) FROM todo_item"
                + " WHERE user_id = :userId AND status = 'DONE' AND due_date = :date",
                userId, date);
    }

    public int countPending(Long userId, LocalDate date) {
        return count("""
                        SELECT COUNT(*) FROM todo_item i
                        WHERE i.user_id = :userId AND i.due_date = :date AND i.status = 'TODO'
                        """, userId, date);
    }

    public int countDeferred(Long userId, LocalDate date) {
        return count("SELECT COUNT(DISTINCT item_id) FROM todo_defer_log"
                + " WHERE user_id = :userId AND from_date = :date", userId, date);
    }

    private int count(String sql, Long userId, LocalDate date) {
        Integer value = jdbc.queryForObject(sql,
                new MapSqlParameterSource()
                        .addValue("userId", userId)
                        .addValue("date", Date.valueOf(date)),
                Integer.class);
        return value == null ? 0 : value;
    }

    public boolean hasDailyStat(Long userId, LocalDate date) {
        Integer value = jdbc.queryForObject(
                "SELECT COUNT(*) FROM todo_daily_stat WHERE user_id = :userId AND stat_date = :date",
                new MapSqlParameterSource()
                        .addValue("userId", userId)
                        .addValue("date", Date.valueOf(date)),
                Integer.class);
        return value != null && value > 0;
    }

    public void upsertDailyStat(Long userId, LocalDate date, int created, int completed,
                                int pending, int deferred, BigDecimal completionRate) {
        jdbc.update("""
                        INSERT INTO todo_daily_stat
                            (user_id, stat_date, created_count, completed_count, pending_count,
                             deferred_count, completion_rate)
                        VALUES
                            (:userId, :date, :created, :completed, :pending, :deferred, :rate)
                        ON DUPLICATE KEY UPDATE
                            created_count = :created,
                            completed_count = :completed,
                            pending_count = :pending,
                            deferred_count = :deferred,
                            completion_rate = :rate
                        """,
                new MapSqlParameterSource()
                        .addValue("userId", userId)
                        .addValue("date", Date.valueOf(date))
                        .addValue("created", created)
                        .addValue("completed", completed)
                        .addValue("pending", pending)
                        .addValue("deferred", deferred)
                        .addValue("rate", completionRate));
    }

    public List<TodoDailyStatDO> listDailyStats(Long userId, LocalDate from, LocalDate to) {
        return jdbc.query("""
                        SELECT stat_date, user_id, created_count, completed_count, pending_count,
                               deferred_count, completion_rate
                        FROM todo_daily_stat
                        WHERE user_id = :userId AND stat_date BETWEEN :from AND :to
                          AND (created_count > 0 OR completed_count > 0 OR pending_count > 0
                               OR deferred_count > 0)
                        ORDER BY stat_date
                        """,
                new MapSqlParameterSource()
                        .addValue("userId", userId)
                        .addValue("from", Date.valueOf(from))
                        .addValue("to", Date.valueOf(to)),
                STAT_MAPPER);
    }

    public List<Long> listActiveUserIds() {
        return jdbc.queryForList(
                "SELECT DISTINCT user_id FROM todo_item", new MapSqlParameterSource(), Long.class);
    }

    private MapSqlParameterSource baseParams(TodoItemDO item) {
        return new MapSqlParameterSource()
                .addValue("userId", item.getUserId())
                .addValue("title", item.getTitle())
                .addValue("note", item.getNote())
                .addValue("dueDate", Date.valueOf(item.getDueDate()))
                .addValue("dueTime", item.getDueTime() == null ? null : Time.valueOf(item.getDueTime()))
                .addValue("status", item.getStatus())
                .addValue("source", item.getSource())
                .addValue("createdAt", Timestamp.valueOf(item.getCreatedAt()))
                .addValue("completedAt", item.getCompletedAt() == null
                        ? null : Timestamp.valueOf(item.getCompletedAt()))
                .addValue("updatedAt", Timestamp.valueOf(item.getUpdatedAt()));
    }
}

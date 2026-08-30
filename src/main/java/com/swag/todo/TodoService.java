package com.swag.todo;

import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;

import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.LocalTime;
import java.time.format.DateTimeParseException;
import java.util.List;

/**
 * 待办业务逻辑，聊天工具与 REST 接口共用。
 */
@Service
public class TodoService {

    private final TodoRepository repository;
    private final TodoStatisticsService statistics;

    public TodoService(
            TodoRepository repository,
            TodoStatisticsService statistics) {
        this.repository = repository;
        this.statistics = statistics;
    }

    @Transactional
    public TodoItemDO create(Long userId, String title, String note,
                             LocalDate dueDate, LocalTime dueTime, String source) {
        if (title == null || title.isBlank()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "待办标题不能为空");
        }
        TodoItemDO item = new TodoItemDO();
        item.setUserId(userId);
        item.setTitle(title.trim());
        item.setNote(note == null || note.isBlank() ? null : note.trim());
        item.setDueDate(dueDate == null ? TodoDates.today() : dueDate);
        item.setDueTime(dueTime);
        item.setStatus("TODO");
        item.setSource(source == null ? "CHAT" : source);
        LocalDateTime now = LocalDateTime.now(TodoDates.ZONE);
        item.setCreatedAt(now);
        item.setUpdatedAt(now);
        TodoItemDO created = repository.insert(item);
        statistics.refreshToday(userId);
        return created;
    }

    public List<TodoItemDO> listToday(Long userId) {
        return repository.listByDate(userId, TodoDates.today());
    }

    public List<TodoItemDO> listByDate(Long userId, LocalDate date) {
        return repository.listByDate(userId, date);
    }

    @Transactional
    public TodoItemDO complete(Long userId, String idOrTitle) {
        TodoItemDO item = resolve(userId, idOrTitle);
        LocalDateTime now = LocalDateTime.now(TodoDates.ZONE);
        repository.complete(item.getId(), userId, now, now);
        item.setStatus("DONE");
        item.setCompletedAt(now);
        item.setUpdatedAt(now);
        statistics.refreshToday(userId);
        return item;
    }

    @Transactional
    public TodoItemDO defer(Long userId, String idOrTitle, LocalDate newDate) {
        if (newDate == null) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "请提供延期目标日期");
        }
        TodoItemDO item = resolve(userId, idOrTitle);
        LocalDate from = item.getDueDate();
        LocalDateTime now = LocalDateTime.now(TodoDates.ZONE);
        repository.updateDueDate(item.getId(), userId, newDate, now);
        repository.insertDeferLog(item.getId(), userId, from, newDate, now);
        item.setDueDate(newDate);
        item.setUpdatedAt(now);
        statistics.refreshToday(userId);
        return item;
    }

    @Transactional
    public TodoItemDO delete(Long userId, String idOrTitle) {
        TodoItemDO item = resolve(userId, idOrTitle);
        repository.delete(item.getId(), userId);
        statistics.refreshToday(userId);
        return item;
    }

    public List<TodoDailyStatDO> stats(Long userId, LocalDate from, LocalDate to) {
        return repository.listDailyStats(userId, from, to);
    }

    /**
     * 按 #id 或标题解析待办；标题模糊匹配到多条时要求改用 #id。
     */
    private TodoItemDO resolve(Long userId, String idOrTitle) {
        String ref = idOrTitle == null ? "" : idOrTitle.trim();
        if (ref.matches("\\d+")) {
            long id = Long.parseLong(ref);
            return repository.findById(id)
                    .filter(i -> i.getUserId().equals(userId))
                    .orElseThrow(() -> new ResponseStatusException(
                            HttpStatus.NOT_FOUND, "待办不存在：#" + id));
        }

        List<TodoItemDO> all = repository.listAll(userId);
        List<TodoItemDO> matches = all.stream()
                .filter(i -> i.getTitle() != null
                        && i.getTitle().toLowerCase().contains(ref.toLowerCase()))
                .toList();
        if (matches.size() == 1) {
            return matches.get(0);
        }
        if (matches.isEmpty()) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "未找到待办：" + ref);
        }
        List<TodoItemDO> exact = matches.stream()
                .filter(i -> i.getTitle().equalsIgnoreCase(ref))
                .toList();
        if (exact.size() == 1) {
            return exact.get(0);
        }
        String ids = matches.stream().map(i -> "#" + i.getId()).toList().toString();
        throw new ResponseStatusException(HttpStatus.BAD_REQUEST,
                "匹配到多条待办，请用 #id 指定：" + ids);
    }

    public LocalDate parseDate(String value, LocalDate fallback) {
        if (value == null || value.isBlank()) {
            return fallback;
        }
        String v = value.trim();
        switch (v.toLowerCase()) {
            case "today", "今天" -> {
                return TodoDates.today();
            }
            case "tomorrow", "明天" -> {
                return TodoDates.tomorrow();
            }
        }
        try {
            return LocalDate.parse(v);
        }
        catch (DateTimeParseException ignored) {
            return fallback;
        }
    }

    public LocalTime parseTime(String value) {
        if (value == null || value.isBlank()) {
            return null;
        }
        try {
            return LocalTime.parse(value.trim());
        }
        catch (DateTimeParseException ignored) {
            return null;
        }
    }
}

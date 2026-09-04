package com.swag.todo;

import org.springframework.stereotype.Service;

import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.LocalDate;

/**
 * 从待办与延期记录重建指定用户的每日统计。
 */
@Service
public class TodoStatisticsService {

    private final TodoRepository repository;

    public TodoStatisticsService(TodoRepository repository) {
        this.repository = repository;
    }

    public void refresh(Long userId, LocalDate date) {
        int created = repository.countCreated(userId, date);
        int completed = repository.countCompleted(userId, date);
        int pending = repository.countPending(userId, date);
        int deferred = repository.countDeferred(userId, date);

        int settled = completed + pending + deferred;
        BigDecimal completionRate = settled == 0
                ? null
                : BigDecimal.valueOf(completed * 100.0 / settled)
                        .setScale(2, RoundingMode.HALF_UP);

        repository.upsertDailyStat(
                userId,
                date,
                created,
                completed,
                pending,
                deferred,
                completionRate);
    }
}

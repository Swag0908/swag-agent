package com.swag.todo;

import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;

import java.time.LocalDate;

/**
 * 每日结算：把「昨天」的待办汇总进按天统计。
 * 历史待办和延期记录会保留，供日历回顾使用。
 */
@Service
public class TodoRolloverService {

    private final TodoRepository repository;
    private final TodoStatisticsService statistics;

    public TodoRolloverService(
            TodoRepository repository,
            TodoStatisticsService statistics) {
        this.repository = repository;
        this.statistics = statistics;
    }

    /**
     * 每日 0 点结算昨天。
     */
    @Scheduled(cron = "0 0 0 * * ?", zone = "Asia/Shanghai")
    public void scheduledRollover() {
        settleAll(TodoDates.today().minusDays(1));
    }

    /**
     * 访问今日清单/统计时的惰性兜底：确保昨天已结算。
     */
    public void ensureSettled(Long userId) {
        settle(userId, TodoDates.today().minusDays(1));
    }

    public void settleAll(LocalDate date) {
        for (Long userId : repository.listActiveUserIds()) {
            settle(userId, date);
        }
    }

    public void settle(Long userId, LocalDate date) {
        if (repository.hasDailyStat(userId, date)) {
            return;
        }
        statistics.refresh(userId, date);
    }
}

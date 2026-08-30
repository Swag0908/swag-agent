package com.swag.todo;

import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Service;

import java.time.LocalDate;

/**
 * 每日结算：把「昨天」的待办汇总进按天统计，并清理超过一周的旧数据。
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
     * 每日 0 点结算最近 7 天（幂等，已结算的跳过），再清理超过一周的数据。
     */
    @Scheduled(cron = "0 0 0 * * ?", zone = "Asia/Shanghai")
    public void scheduledRollover() {
        LocalDate today = TodoDates.today();
        for (int d = 1; d <= 7; d++) {
            settleAll(today.minusDays(d));
        }
        for (Long userId : repository.listActiveUserIds()) {
            repository.deleteDueBefore(userId, today.minusDays(7));
            repository.deleteDeferLogsBefore(userId, today.minusDays(7));
        }
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

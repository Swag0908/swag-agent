package com.swag.todo;

import org.junit.jupiter.api.Test;

import java.math.BigDecimal;
import java.time.LocalDate;

import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class TodoStatisticsServiceTests {

    @Test
    void refreshRebuildsCountsAndCompletionRate() {
        TodoRepository repository = mock(TodoRepository.class);
        TodoStatisticsService service = new TodoStatisticsService(repository);
        LocalDate date = LocalDate.of(2026, 8, 30);
        when(repository.countCreated(7L, date)).thenReturn(5);
        when(repository.countCompleted(7L, date)).thenReturn(2);
        when(repository.countPending(7L, date)).thenReturn(1);
        when(repository.countDeferred(7L, date)).thenReturn(1);

        service.refresh(7L, date);

        verify(repository).upsertDailyStat(
                7L,
                date,
                5,
                2,
                1,
                1,
                new BigDecimal("50.00"));
    }
}

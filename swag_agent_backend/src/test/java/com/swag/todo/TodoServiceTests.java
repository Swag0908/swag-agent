package com.swag.todo;

import org.junit.jupiter.api.Test;

import java.time.LocalDate;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class TodoServiceTests {

    @Test
    void completingTodoRefreshesTodayStatistics() {
        TodoRepository repository = mock(TodoRepository.class);
        TodoStatisticsService statistics = mock(TodoStatisticsService.class);
        TodoService service = new TodoService(repository, statistics);
        TodoItemDO item = todo(42L, 7L);
        when(repository.findById(42L)).thenReturn(Optional.of(item));

        TodoItemDO completed = service.complete(7L, "42");

        assertThat(completed.getStatus()).isEqualTo("DONE");
        assertThat(completed.getCompletedAt()).isNotNull();
        verify(repository).complete(any(), any(), any(), any());
        verify(statistics).refreshToday(7L);
    }

    private TodoItemDO todo(Long id, Long userId) {
        TodoItemDO item = new TodoItemDO();
        item.setId(id);
        item.setUserId(userId);
        item.setTitle("写文档");
        item.setDueDate(LocalDate.now(TodoDates.ZONE));
        item.setStatus("TODO");
        return item;
    }
}

package com.swag.todo;

import org.junit.jupiter.api.Test;

import java.time.LocalDate;
import java.time.LocalTime;
import java.util.Optional;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.mock;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;

class TodoServiceTests {

    @Test
    void completingTodoRefreshesItsDueDateStatistics() {
        TodoRepository repository = mock(TodoRepository.class);
        TodoStatisticsService statistics = mock(TodoStatisticsService.class);
        TodoService service = new TodoService(repository, statistics);
        TodoItemDO item = todo(42L, 7L);
        when(repository.findById(42L)).thenReturn(Optional.of(item));

        TodoItemDO completed = service.complete(7L, "42");

        assertThat(completed.getStatus()).isEqualTo("DONE");
        assertThat(completed.getCompletedAt()).isNotNull();
        verify(repository).complete(any(), any(), any(), any());
        verify(statistics).refresh(7L, item.getDueDate());
    }

    @Test
    void creatingFutureTodoRefreshesItsDueDate() {
        TodoRepository repository = mock(TodoRepository.class);
        TodoStatisticsService statistics = mock(TodoStatisticsService.class);
        TodoService service = new TodoService(repository, statistics);
        LocalDate future = TodoDates.today().plusDays(5);
        when(repository.insert(any())).thenAnswer(invocation -> invocation.getArgument(0));

        TodoItemDO created = service.create(7L, "看电影", null, future,
                LocalTime.of(20, 30), "MANUAL");

        assertThat(created.getDueDate()).isEqualTo(future);
        assertThat(created.getDueTime()).isEqualTo(LocalTime.of(20, 30));
        verify(statistics).refresh(7L, future);
    }

    @Test
    void updatingTodoRefreshesOldAndNewDates() {
        TodoRepository repository = mock(TodoRepository.class);
        TodoStatisticsService statistics = mock(TodoStatisticsService.class);
        TodoService service = new TodoService(repository, statistics);
        LocalDate oldDate = TodoDates.today();
        LocalDate newDate = oldDate.plusDays(3);
        TodoItemDO item = todo(42L, 7L);
        when(repository.findById(42L)).thenReturn(Optional.of(item));

        TodoItemDO updated = service.update(7L, "42", "新标题", "新备注",
                newDate, LocalTime.of(9, 15));

        assertThat(updated.getTitle()).isEqualTo("新标题");
        assertThat(updated.getDueDate()).isEqualTo(newDate);
        assertThat(updated.getDueTime()).isEqualTo(LocalTime.of(9, 15));
        verify(repository).update(item);
        verify(statistics).refresh(7L, oldDate);
        verify(statistics).refresh(7L, newDate);
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

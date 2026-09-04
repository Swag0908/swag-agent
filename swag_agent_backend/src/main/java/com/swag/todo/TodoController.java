package com.swag.todo;

import com.swag.auth.UserContextHolder;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PatchMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

import java.math.BigDecimal;
import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.LocalTime;
import java.util.List;

/**
 * 待办与统计 REST 接口（供前端侧栏与统计页使用）。
 */
@RestController
@RequestMapping("/todo")
public class TodoController {

    public record CreateRequest(String title, String note, String dueDate, String dueTime) {
    }

    public record UpdateRequest(String title, String note, String dueDate, String dueTime) {
    }

    public record DeferRequest(String newDate) {
    }

    public record ItemResponse(Long id, String title, String note, LocalDate dueDate, LocalTime dueTime,
                               String status, String source, LocalDateTime createdAt,
                               LocalDateTime completedAt) {
        static ItemResponse from(TodoItemDO item) {
            return new ItemResponse(item.getId(), item.getTitle(), item.getNote(), item.getDueDate(),
                    item.getDueTime(), item.getStatus(), item.getSource(),
                    item.getCreatedAt(), item.getCompletedAt());
        }
    }

    public record StatResponse(LocalDate statDate, int createdCount, int completedCount,
                               int pendingCount, int deferredCount, BigDecimal completionRate) {
        static StatResponse from(TodoDailyStatDO stat) {
            return new StatResponse(stat.getStatDate(), stat.getCreatedCount(),
                    stat.getCompletedCount(), stat.getPendingCount(),
                    stat.getDeferredCount(), stat.getCompletionRate());
        }
    }

    private final TodoService service;
    private final TodoRolloverService rollover;

    public TodoController(TodoService service, TodoRolloverService rollover) {
        this.service = service;
        this.rollover = rollover;
    }

    @GetMapping("/today")
    public List<ItemResponse> today() {
        Long userId = currentUser();
        rollover.ensureSettled(userId);
        return service.listToday(userId).stream().map(ItemResponse::from).toList();
    }

    @PostMapping
    public ItemResponse create(@RequestBody CreateRequest request) {
        TodoItemDO item = service.create(currentUser(), request.title(), request.note(),
                service.parseDate(request.dueDate(), TodoDates.today()),
                service.parseTime(request.dueTime()),
                "MANUAL");
        return ItemResponse.from(item);
    }

    @GetMapping
    public List<ItemResponse> range(@RequestParam String from, @RequestParam String to) {
        LocalDate fromDate = requiredDate(from, "请提供开始日期");
        LocalDate toDate = requiredDate(to, "请提供结束日期");
        return service.listByDateRange(currentUser(), fromDate, toDate).stream()
                .map(ItemResponse::from)
                .toList();
    }

    @PatchMapping("/{id}")
    public ItemResponse update(@PathVariable Long id, @RequestBody UpdateRequest request) {
        TodoItemDO item = service.update(currentUser(), id.toString(), request.title(), request.note(),
                requiredDate(request.dueDate(), "请选择待办日期"),
                service.parseTime(request.dueTime()));
        return ItemResponse.from(item);
    }

    @PatchMapping("/{id}/complete")
    public ItemResponse complete(@PathVariable Long id) {
        return ItemResponse.from(service.complete(currentUser(), id.toString()));
    }

    @PatchMapping("/{id}/defer")
    public ItemResponse defer(@PathVariable Long id, @RequestBody DeferRequest request) {
        return ItemResponse.from(service.defer(currentUser(), id.toString(),
                service.parseDate(request.newDate(), TodoDates.tomorrow())));
    }

    @DeleteMapping("/{id}")
    public void delete(@PathVariable Long id) {
        service.delete(currentUser(), id.toString());
    }

    @GetMapping("/stats/daily")
    public List<StatResponse> stats(
            @RequestParam(required = false) String from,
            @RequestParam(required = false) String to) {
        Long userId = currentUser();
        rollover.ensureSettled(userId);
        LocalDate toDate = service.parseDate(to, TodoDates.today());
        LocalDate fromDate = service.parseDate(from, toDate.minusDays(6));
        return service.stats(userId, fromDate, toDate).stream().map(StatResponse::from).toList();
    }

    private Long currentUser() {
        Long userId = UserContextHolder.currentUserId();
        if (userId == null) {
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "未登录");
        }
        return userId;
    }

    private LocalDate requiredDate(String value, String message) {
        LocalDate parsed = service.parseDate(value, null);
        if (parsed == null) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, message);
        }
        return parsed;
    }
}

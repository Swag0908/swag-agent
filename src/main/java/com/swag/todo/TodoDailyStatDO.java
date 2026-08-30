package com.swag.todo;

import lombok.Data;

import java.math.BigDecimal;
import java.time.LocalDate;

/**
 * 按天统计实体。
 */
@Data
public class TodoDailyStatDO {
    private LocalDate statDate;
    private Long userId;
    private int createdCount;
    private int completedCount;
    private int pendingCount;
    private int deferredCount;
    private BigDecimal completionRate;
}

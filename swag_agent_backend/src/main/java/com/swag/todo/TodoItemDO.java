package com.swag.todo;

import lombok.Data;

import java.time.LocalDate;
import java.time.LocalDateTime;
import java.time.LocalTime;

/**
 * 待办条目实体。
 */
@Data
public class TodoItemDO {
    private Long id;
    private Long userId;
    private String title;
    private String note;
    /** 目标日，默认创建当天；「延期」即修改该日期。 */
    private LocalDate dueDate;
    /** 当天的计划时间（可选）。 */
    private LocalTime dueTime;
    /** TODO / DONE。 */
    private String status;
    /** CHAT / MANUAL。 */
    private String source;
    private LocalDateTime createdAt;
    private LocalDateTime completedAt;
    private LocalDateTime updatedAt;
}

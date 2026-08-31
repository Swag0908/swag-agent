-- 当日待办工作区（滚动保留最近一周）、延期事件与按天统计。
CREATE TABLE todo_item (
    id           BIGINT       NOT NULL AUTO_INCREMENT,
    user_id      BIGINT       NOT NULL,
    title        VARCHAR(255) NOT NULL,
    note         TEXT         NULL,
    due_date     DATE         NOT NULL,
    due_time     TIME         NULL,
    status       VARCHAR(16)  NOT NULL DEFAULT 'TODO',
    source       VARCHAR(16)  NOT NULL DEFAULT 'CHAT',
    created_at   DATETIME(6)  NOT NULL,
    completed_at DATETIME(6)  NULL,
    updated_at   DATETIME(6)  NOT NULL,
    PRIMARY KEY (id),
    KEY idx_todo_user_due_status (user_id, due_date, status),
    KEY idx_todo_user_created (user_id, created_at)
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4;

-- 「延期」事件：from_date 用于统计该日期被延期走了多少条。
CREATE TABLE todo_defer_log (
    id          BIGINT      NOT NULL AUTO_INCREMENT,
    item_id     BIGINT      NOT NULL,
    user_id     BIGINT      NOT NULL,
    from_date   DATE        NOT NULL,
    to_date     DATE        NOT NULL,
    deferred_at DATETIME(6) NOT NULL,
    PRIMARY KEY (id),
    KEY idx_defer_user_from (user_id, from_date)
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4;

-- 按天统计：已完成 / 未完成 / 延期（至明天或指定日期）/ 当日新增。
CREATE TABLE todo_daily_stat (
    stat_date       DATE         NOT NULL,
    user_id         BIGINT       NOT NULL,
    created_count   INT          NOT NULL DEFAULT 0,
    completed_count INT          NOT NULL DEFAULT 0,
    pending_count   INT          NOT NULL DEFAULT 0,
    deferred_count  INT          NOT NULL DEFAULT 0,
    completion_rate DECIMAL(5, 2) NULL,
    PRIMARY KEY (user_id, stat_date)
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4;

package com.swag.todo;

import java.time.LocalDate;
import java.time.ZoneId;

/**
 * 待办日期统一按中国时区（Asia/Shanghai）计算，避免「今天/明天」跨天边界漂移。
 */
public final class TodoDates {

    public static final ZoneId ZONE = ZoneId.of("Asia/Shanghai");

    private TodoDates() {
    }

    public static LocalDate today() {
        return LocalDate.now(ZONE);
    }

    public static LocalDate tomorrow() {
        return today().plusDays(1);
    }
}

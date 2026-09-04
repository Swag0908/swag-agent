package com.swag.notes;

import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

/**
 * 每天凌晨清理各用户回收站中超过 7 天的条目（读取回收站时也会顺带清理）。
 */
@Component
public class NotesTrashCleaner {

    private final NotesService service;

    public NotesTrashCleaner(NotesService service) {
        this.service = service;
    }

    @Scheduled(cron = "0 30 3 * * *")
    public void purgeExpiredTrash() {
        service.purgeAllExpired();
    }
}

package com.swag.notes;

import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.stereotype.Component;

/**
 * Markdown 笔记模块配置。
 * <p>
 * 笔记一律以 {@code .md} 文件存放在服务器磁盘：{@code <root>/user-<userId>} 为每个用户的
 * 专属笔记目录（"按用户维度存放笔记"）。root 通过配置项 {@code app.notes.root} 指定，
 * 例如生产环境可设为 {@code /opt/swag_agent/notes}。
 */
@Data
@Component
@ConfigurationProperties(prefix = "app.notes")
public class NotesProperties {

    /** 所有用户笔记文件的公共根目录。 */
    private String root = "./notes-data";
}

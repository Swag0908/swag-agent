package com.swag.notes;

import lombok.Data;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.List;

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

    /**
     * 允许按服务器本地绝对路径导入 Markdown 的根目录。每个来源及其引用的本地附件解析真实路径后，
     * 都必须落在其中一个根目录内；空列表表示关闭本地路径导入。
     */
    private List<String> importRoots = new ArrayList<>();

    /** 单篇导入的 Markdown 原文件上限。 */
    private long maxImportMarkdownBytes = 2L * 1024 * 1024;

    /** 单个引用附件上限。 */
    private long maxImportAttachmentBytes = 20L * 1024 * 1024;

    /** 一次批量导入（Markdown + 附件）的总读取上限。 */
    private long maxImportTotalBytes = 100L * 1024 * 1024;
}

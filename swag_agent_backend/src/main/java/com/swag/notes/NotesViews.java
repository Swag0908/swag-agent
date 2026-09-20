package com.swag.notes;

import java.util.List;

/**
 * Markdown 笔记 REST 视图对象。
 */
public final class NotesViews {

    private NotesViews() {
    }

    /** 目录树节点：dir 带 children，file 无 children。 */
    public record Node(String name, String path, String type, List<Node> children) {
    }

    /** 一篇笔记的完整内容。 */
    public record FileView(String path, String name, long size, long modified, String content) {
    }

    /** 保存成功后的回执。 */
    public record SaveResult(String path, long size, long modified) {
    }

    /** 单个导入来源的失败信息；批量导入不会因为其中一个坏文件放弃其它文件。 */
    public record ImportFailure(String source, String reason) {
    }

    /** 批量导入结果：imported 是实际落盘路径（重名时会自动加序号）。 */
    public record ImportResult(List<String> imported, List<ImportFailure> failed,
                               List<String> warnings, int attachmentsCopied) {
    }

    /** 前端展示用的导入边界，避免把服务端配置路径硬编码进页面。 */
    public record ImportConfig(List<String> localRoots) {
    }

    /** 读取导入附件时返回的内部资源描述。 */
    public record ResourceView(org.springframework.core.io.Resource resource,
                               String fileName, String contentType, boolean inline) {
    }

    /** 回收站条目。kind: file | dir；deletedAt 为毫秒时间戳。 */
    public record TrashView(String id, String originalPath, String name, String kind, long deletedAt) {
    }
}

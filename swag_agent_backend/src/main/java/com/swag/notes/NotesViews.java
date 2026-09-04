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

    /** 回收站条目。kind: file | dir；deletedAt 为毫秒时间戳。 */
    public record TrashView(String id, String originalPath, String name, String kind, long deletedAt) {
    }
}

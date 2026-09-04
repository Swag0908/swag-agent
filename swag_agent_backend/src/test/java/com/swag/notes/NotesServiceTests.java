package com.swag.notes;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.web.server.ResponseStatusException;

import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 笔记服务的读写、回收站、未分类与路径安全测试。
 */
class NotesServiceTests {

    @TempDir
    Path tempDir;

    NotesService service;
    NotesProperties properties;

    @BeforeEach
    void setUp() {
        properties = new NotesProperties();
        properties.setRoot(tempDir.toString());
        service = new NotesService(properties);
    }

    // ---------- 基本读写 ----------

    @Test
    void saveAndReadRoundTrip() {
        service.createDir(7L, "工作");
        service.save(7L, "工作/周报.md", "# 标题\n\n正文内容");

        NotesViews.FileView view = service.read(7L, "工作/周报.md");
        assertEquals("周报.md", view.name());
        assertEquals("# 标题\n\n正文内容", view.content());
        assertTrue(view.size() > 0);

        // 每个用户目录相互隔离
        assertThrows(ResponseStatusException.class, () -> service.read(8L, "工作/周报.md"));
    }

    @Test
    void treeListsMdFilesAndDirectoriesSorted() throws Exception {
        service.createDir(1L, "a目录/子");
        service.save(1L, "b笔记.md", "b");
        service.save(1L, "a目录/子/a笔记.md", "a");
        // 直接落盘一个非 md 文件，验证它不会出现在目录树里
        Path ignored = tempDir.resolve("user-1").resolve("a目录").resolve("忽略.txt");
        Files.createDirectories(ignored.getParent());
        Files.writeString(ignored, "x");

        NotesViews.Node root = service.tree(1L);
        assertEquals("dir", root.type());
        // 目录排前：a目录、未分类(默认) + b笔记.md
        assertEquals(3, root.children().size());
        assertEquals("a目录", root.children().get(0).name());
        assertEquals(NotesService.UNCLASSIFIED, root.children().get(1).name());
        assertEquals("b笔记.md", root.children().get(2).name());

        NotesViews.Node dir = root.children().get(0);
        assertEquals(1, dir.children().size());
        NotesViews.Node sub = dir.children().get(0);
        assertEquals("子", sub.name());
        assertEquals(1, sub.children().size());
        assertEquals("a笔记.md", sub.children().get(0).name());
        assertEquals("a目录/子/a笔记.md", sub.children().get(0).path());
    }

    @Test
    void defaultUnclassifiedFolderSeeded() {
        NotesViews.Node root = service.tree(99L);
        assertTrue(root.children().stream().anyMatch(
                n -> n.type().equals("dir") && n.name().equals(NotesService.UNCLASSIFIED)),
                "每个用户默认应有「未分类」文件夹");
    }

    @Test
    void renameMovesFileAndDir() {
        service.createDir(2L, "子目录");
        service.save(2L, "old.md", "内容");
        service.rename(2L, "old.md", "子目录/new.md");
        assertEquals("内容", service.read(2L, "子目录/new.md").content());
        assertThrows(ResponseStatusException.class, () -> service.read(2L, "old.md"));

        service.createDir(2L, "folder");
        service.save(2L, "folder/a.md", "a");
        service.rename(2L, "folder", "子目录/moved");
        assertEquals("a", service.read(2L, "子目录/moved/a.md").content());
    }

    // ---------- 回收站 ----------

    @Test
    void deleteFileGoesToTrashAndRestoresToOriginal() {
        service.createDir(7L, "工作");
        service.save(7L, "工作/周报.md", "内容");
        service.deleteFile(7L, "工作/周报.md");

        assertThrows(ResponseStatusException.class, () -> service.read(7L, "工作/周报.md"));
        var trash = service.listTrash(7L);
        assertEquals(1, trash.size());
        assertEquals("file", trash.get(0).kind());
        assertEquals("工作/周报.md", trash.get(0).originalPath());
        assertEquals("周报.md", trash.get(0).name());

        service.restore(7L, trash.get(0).id());
        assertEquals("内容", service.read(7L, "工作/周报.md").content());
        assertEquals(0, service.listTrash(7L).size());
    }

    @Test
    void restoreFallsBackToUnclassifiedWhenParentMissing() {
        service.createDir(7L, "老目录");
        service.save(7L, "老目录/旧笔记.md", "v");
        service.deleteFile(7L, "老目录/旧笔记.md");
        // 把原目录也删掉（整体进回收站），让原目录不存在
        service.deleteDirToTrash(7L, "老目录");

        var trash = service.listTrash(7L);
        NotesViews.TrashView fileItem = trash.stream()
                .filter(t -> t.kind().equals("file")).findFirst().orElseThrow();
        service.restore(7L, fileItem.id());

        assertEquals("v", service.read(7L, "未分类/旧笔记.md").content());
    }

    @Test
    void trashWholeFolderAndRestoreKeepsTree() {
        service.createDir(7L, "项目/子");
        service.save(7L, "项目/a.md", "a");
        service.save(7L, "项目/子/b.md", "b");
        service.deleteDirToTrash(7L, "项目");

        NotesViews.Node root = service.tree(7L);
        assertFalse(root.children().stream().anyMatch(n -> n.name().equals("项目")));
        var trash = service.listTrash(7L);
        assertEquals(1, trash.size());
        assertEquals("dir", trash.get(0).kind());

        service.restore(7L, trash.get(0).id());
        assertEquals("a", service.read(7L, "项目/a.md").content());
        assertEquals("b", service.read(7L, "项目/子/b.md").content());
    }

    @Test
    void deleteDirFlattenMovesNotesToUnclassified() {
        service.createDir(7L, "项目/子");
        service.save(7L, "项目/a.md", "a");
        service.save(7L, "项目/子/b.md", "b");
        service.deleteDirFlatten(7L, "项目");

        assertThrows(ResponseStatusException.class, () -> service.read(7L, "项目/a.md"));
        assertEquals("a", service.read(7L, "未分类/a.md").content());
        assertEquals("b", service.read(7L, "未分类/b.md").content());
        assertEquals(0, service.listTrash(7L).size()); // 平铺模式不占用回收站
    }

    @Test
    void flattenResolvesNameConflict() {
        service.save(7L, "未分类/a.md", "旧的");
        service.createDir(7L, "项目");
        service.save(7L, "项目/a.md", "新的");
        service.deleteDirFlatten(7L, "项目");

        assertEquals("旧的", service.read(7L, "未分类/a.md").content());
        assertEquals("新的", service.read(7L, "未分类/a (1).md").content());
    }

    @Test
    void expiredTrashEntriesPurgedOnList() throws Exception {
        service.save(7L, "旧笔记.md", "v");
        service.deleteFile(7L, "旧笔记.md");

        Path entryDir;
        try (var stream = Files.list(tempDir.resolve("user-7").resolve(".trash"))) {
            entryDir = stream.findFirst().orElseThrow();
        }
        long expired = System.currentTimeMillis() - 8L * 24 * 3600 * 1000;
        Files.writeString(entryDir.resolve("entry.json"),
                "originalPath=旧笔记.md\nkind=file\ndeletedAt=" + expired + "\n",
                StandardCharsets.UTF_8);

        assertTrue(service.listTrash(7L).isEmpty(), "过期条目应被自动清理");
    }

    @Test
    void permanentDeleteRemovesEntry() {
        service.save(7L, "x.md", "x");
        service.deleteFile(7L, "x.md");
        String id = service.listTrash(7L).get(0).id();
        service.deleteTrashEntry(7L, id);
        assertEquals(0, service.listTrash(7L).size());
    }

    // ---------- 路径穿越防护 ----------

    @Test
    void rejectsTraversalAndAbsolutePaths() {
        assertBad(() -> service.save(3L, "../escape.md", "x"));
        assertBad(() -> service.save(3L, "a/../../escape.md", "x"));
        assertBad(() -> service.save(3L, "a//b.md", "x"));
        assertBad(() -> service.save(3L, "a/./b.md", "x"));
        assertBad(() -> service.save(3L, "/etc/escape.md", "x"));
        assertBad(() -> service.save(3L, "..\\escape.md", "x"));
        // 以点开头的保留段（回收站 .trash 等）不可通过普通接口访问
        assertBad(() -> service.save(3L, ".trash/x.md", "x"));
        assertBad(() -> service.save(3L, "工作/.hidden/x.md", "x"));

        assertFalse(Files.exists(tempDir.resolve("escape.md")));
        assertFalse(Files.exists(tempDir.resolve("user-3").resolve("escape.md")));
    }

    @Test
    void rejectsNonMarkdownFileOperations() {
        assertBad(() -> service.save(4L, "note.txt", "x"));
        assertBad(() -> service.deleteFile(4L, "note.md")); // 不存在返回 404
        service.save(4L, "ok.md", "x");
        assertBad(() -> service.rename(4L, "ok.md", "bad.txt"));
    }

    @Test
    void rejectsSymlinkEscape() throws Exception {
        Path outside = Files.createDirectory(tempDir.resolve("outside"));
        Path home = Files.createDirectories(tempDir.resolve("user-5"));
        try {
            Files.createSymbolicLink(home.resolve("link"), outside);
        }
        catch (UnsupportedOperationException | java.io.IOException e) {
            return; // 平台不支持符号链接则跳过
        }

        ResponseStatusException ex = assertThrows(ResponseStatusException.class,
                () -> service.save(5L, "link/escape.md", "x"));
        assertTrue(ex.getStatusCode().value() >= 400);
        assertFalse(Files.exists(outside.resolve("escape.md")));
    }

    private void assertBad(Runnable action) {
        ResponseStatusException ex = assertThrows(ResponseStatusException.class, action::run);
        assertTrue(ex.getStatusCode().value() >= 400, "应为 4xx/5xx，实际：" + ex.getStatusCode());
    }
}

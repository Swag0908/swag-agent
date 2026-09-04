package com.swag.notes;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.web.server.ResponseStatusException;

import java.nio.file.Files;
import java.nio.file.Path;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

/**
 * 笔记服务的路径安全与基本读写测试。
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
        assertEquals(2, root.children().size());
        // 目录排在文件前
        assertEquals("a目录", root.children().get(0).name());
        assertEquals("b笔记.md", root.children().get(1).name());

        NotesViews.Node dir = root.children().get(0);
        assertEquals(1, dir.children().size());
        NotesViews.Node sub = dir.children().get(0);
        assertEquals("子", sub.name());
        assertEquals(1, sub.children().size());
        assertEquals("a笔记.md", sub.children().get(0).name());
        assertEquals("a目录/子/a笔记.md", sub.children().get(0).path());
    }

    @Test
    void deleteAndRename() {
        service.save(2L, "old.md", "内容");
        service.createDir(2L, "子目录");
        service.rename(2L, "old.md", "子目录/new.md");

        assertEquals("内容", service.read(2L, "子目录/new.md").content());
        assertThrows(ResponseStatusException.class, () -> service.read(2L, "old.md"));

        service.deleteFile(2L, "子目录/new.md");
        assertThrows(ResponseStatusException.class, () -> service.read(2L, "子目录/new.md"));
    }

    // ---------- 路径穿越防护 ----------

    @Test
    void rejectsTraversalAndAbsolutePaths() {
        assertBad(() -> service.save(3L, "../escape.md", "x"));
        assertBad(() -> service.save(3L, "a/../../escape.md", "x"));
        assertBad(() -> service.save(3L, "a//b.md", "x"));
        assertBad(() -> service.save(3L, "a/./b.md", "x"));
        // 绝对路径按相对路径处理，仍必须落在用户目录内
        assertBad(() -> service.save(3L, "/etc/escape.md", "x"));
        // Windows 分隔符与穿越组合同样拒绝
        assertBad(() -> service.save(3L, "..\\escape.md", "x"));

        // 非法写入后，用户目录外不应产生任何文件
        assertFalse(Files.exists(tempDir.resolve("escape.md")));
        assertFalse(Files.exists(tempDir.resolve("user-3").resolve("escape.md")));
    }

    @Test
    void rejectsNonMarkdownFileOperations() {
        assertBad(() -> service.save(4L, "note.txt", "x"));
        assertBad(() -> service.deleteFile(4L, "note.md")); // 不存在返回 404，先建再删
        service.save(4L, "ok.md", "x");
        assertBad(() -> service.rename(4L, "ok.md", "bad.txt"));
    }

    @Test
    void rejectsSymlinkEscape() throws Exception {
        // 在用户目录外放一个目录，并在用户目录内做符号链接指向它
        Path outside = Files.createDirectory(tempDir.resolve("outside"));
        Path home = Files.createDirectories(tempDir.resolve("user-5"));
        try {
            Files.createSymbolicLink(home.resolve("link"), outside);
        }
        catch (UnsupportedOperationException | java.io.IOException e) {
            // 平台不支持符号链接则跳过
            return;
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

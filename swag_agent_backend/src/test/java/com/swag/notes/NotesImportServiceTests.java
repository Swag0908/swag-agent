package com.swag.notes;

import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.junit.jupiter.api.io.TempDir;
import org.springframework.mock.web.MockMultipartFile;

import java.net.URLDecoder;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.List;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

import static org.junit.jupiter.api.Assertions.assertArrayEquals;
import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertTrue;

class NotesImportServiceTests {

    private static final Pattern RESOURCE_URL = Pattern.compile(
            "/api/notes/resource\\?bundle=([0-9a-f-]{36})&name=([^\\s)\"']+)");

    @TempDir
    Path tempDir;

    private Path allowedRoot;
    private NotesService notes;
    private NotesImportService importer;

    @BeforeEach
    void setUp() throws Exception {
        allowedRoot = Files.createDirectories(tempDir.resolve("imports"));
        NotesProperties properties = new NotesProperties();
        properties.setRoot(tempDir.resolve("notes").toString());
        properties.setImportRoots(List.of(allowedRoot.toString()));
        notes = new NotesService(properties);
        importer = new NotesImportService(notes, properties);
        notes.createDir(7L, "目标");
    }

    @Test
    void importsPlainMarkdownAndCopiesReferencedLocalFiles() throws Exception {
        Path sourceDir = Files.createDirectories(allowedRoot.resolve("article"));
        Files.createDirectories(sourceDir.resolve("images"));
        Files.createDirectories(sourceDir.resolve("files"));
        Files.write(sourceDir.resolve("images/pic.png"), new byte[]{1, 2, 3});
        Files.writeString(sourceDir.resolve("files/data.txt"), "data", StandardCharsets.UTF_8);
        Files.writeString(sourceDir.resolve("helper.js"), "alert('not executed')", StandardCharsets.UTF_8);
        Files.write(sourceDir.resolve("absolute.png"), new byte[]{4, 5, 6});
        Path markdown = sourceDir.resolve("随手记.md");
        Files.writeString(markdown, ("""
                没有 frontmatter 也可以。

                ![图](images/pic.png)
                [附件](files/data.txt)
                <script src="helper.js"></script>
                """ + "![绝对图片](" + sourceDir.resolve("absolute.png").toUri() + ")\n"), StandardCharsets.UTF_8);

        NotesViews.ImportResult result = importer.importLocal(
                7L, List.of(markdown.toString()), "目标");

        assertEquals(List.of("目标/随手记.md"), result.imported());
        assertEquals(4, result.attachmentsCopied());
        assertTrue(result.failed().isEmpty());
        String content = notes.read(7L, "目标/随手记.md").content();
        assertTrue(content.contains("没有 frontmatter 也可以"));
        assertFalse(content.contains("images/pic.png"));
        assertEquals(4, countResourceUrls(content));

        Matcher first = RESOURCE_URL.matcher(content);
        assertTrue(first.find());
        NotesViews.ResourceView resource = importer.resource(
                7L, first.group(1), URLDecoder.decode(first.group(2), StandardCharsets.UTF_8));
        assertArrayEquals(new byte[]{1, 2, 3}, resource.resource().getInputStream().readAllBytes());
        assertTrue(resource.inline());
    }

    @Test
    void importsMultipleFilesAndNeverOverwritesSameName() throws Exception {
        Path one = Files.createDirectories(allowedRoot.resolve("one")).resolve("same.md");
        Path two = Files.createDirectories(allowedRoot.resolve("two")).resolve("same.md");
        Files.writeString(one, "one", StandardCharsets.UTF_8);
        Files.writeString(two, "two", StandardCharsets.UTF_8);

        NotesViews.ImportResult result = importer.importLocal(
                7L, List.of(one.toString(), two.toString()), "目标");

        assertEquals(List.of("目标/same.md", "目标/same (1).md"), result.imported());
        assertEquals("one", notes.read(7L, "目标/same.md").content());
        assertEquals("two", notes.read(7L, "目标/same (1).md").content());
    }

    @Test
    void localImportRejectsFilesOutsideConfiguredRootsWithoutStoppingBatch() throws Exception {
        Path valid = allowedRoot.resolve("valid.md");
        Path outside = tempDir.resolve("outside.md");
        Files.writeString(valid, "ok", StandardCharsets.UTF_8);
        Files.writeString(outside, "secret", StandardCharsets.UTF_8);

        NotesViews.ImportResult result = importer.importLocal(
                7L, List.of(outside.toString(), valid.toString()), "目标");

        assertEquals(List.of("目标/valid.md"), result.imported());
        assertEquals(1, result.failed().size());
        assertTrue(result.failed().getFirst().reason().contains("不在允许导入的目录内"));
    }

    @Test
    void folderUploadResolvesRelativeAttachmentsAndImportsEveryMarkdown() throws Exception {
        MockMultipartFile first = new MockMultipartFile(
                "files", "first.md", "text/markdown", "![x](img/p.png)".getBytes(StandardCharsets.UTF_8));
        MockMultipartFile second = new MockMultipartFile(
                "files", "second.md", "text/markdown", "普通文本".getBytes(StandardCharsets.UTF_8));
        MockMultipartFile image = new MockMultipartFile(
                "files", "p.png", "image/png", new byte[]{9, 8, 7});

        NotesViews.ImportResult result = importer.importUploads(7L, List.of(
                new NotesImportService.UploadPart("bundle/first.md", first),
                new NotesImportService.UploadPart("bundle/second.md", second),
                new NotesImportService.UploadPart("bundle/img/p.png", image)), "目标");

        assertEquals(List.of("目标/first.md", "目标/second.md"), result.imported());
        assertEquals(1, result.attachmentsCopied());
        assertTrue(notes.read(7L, "目标/first.md").content().contains("/api/notes/resource?"));
        assertEquals("普通文本", notes.read(7L, "目标/second.md").content());
    }

    @Test
    void acceptsEmptyMarkdownUploadWithoutFormatRequirements() {
        MockMultipartFile empty = new MockMultipartFile(
                "files", "empty.md", "text/markdown", new byte[0]);

        NotesViews.ImportResult result = importer.importUploads(7L, List.of(
                new NotesImportService.UploadPart("empty.md", empty)), "目标");

        assertEquals(List.of("目标/empty.md"), result.imported());
        assertEquals("", notes.read(7L, "目标/empty.md").content());
    }

    private int countResourceUrls(String content) {
        int count = 0;
        Matcher matcher = RESOURCE_URL.matcher(content);
        while (matcher.find()) count++;
        return count;
    }
}

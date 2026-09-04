package com.swag.notes;

import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.server.ResponseStatusException;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.nio.file.StandardOpenOption;
import java.util.ArrayDeque;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.Deque;
import java.util.List;

/**
 * Markdown 笔记的磁盘读写服务。
 * <p>
 * 笔记文件存放在服务器磁盘 {@code <app.notes.root>/user-<userId>}（按用户维度隔离）。
 * 对外全部使用相对路径（以 / 分隔，如 {@code 工作/周报.md}），本服务负责：
 * <ul>
 *   <li>把相对路径安全解析到用户目录内（拒绝 {@code ..}、绝对路径、符号链接逃逸）；</li>
 *   <li>递归列目录树（只列出 .md 笔记与文件夹，忽略隐藏项与符号链接）；</li>
 *   <li>文件的读 / 写 / 删、目录的新建 / 删除、文件或目录的重命名。</li>
 * </ul>
 */
@Service
public class NotesService {

    /** 单个笔记文件大小上限（2 MiB）。 */
    private static final long MAX_NOTE_BYTES = 2L * 1024 * 1024;

    private final NotesProperties properties;

    public NotesService(NotesProperties properties) {
        this.properties = properties;
    }

    // ---------- 对外操作 ----------

    /** 返回用户笔记目录的树（根为用户的专属目录）。 */
    public NotesViews.Node tree(Long userId) {
        try {
            return buildNode(ensureHome(userId), "user-" + userId, "");
        }
        catch (IOException e) {
            throw ioError("读取笔记目录失败", e);
        }
    }

    /** 读取一篇笔记的源码与元信息。 */
    public NotesViews.FileView read(Long userId, String rel) {
        Path home = ensureHome(userId);
        Path file = guard(home, rel);
        if (!Files.exists(file)) {
            throw notFound("笔记不存在：" + rel);
        }
        if (Files.isDirectory(file)) {
            throw badRequest("「" + rel + "」是文件夹，不是笔记文件");
        }
        try {
            long size = Files.size(file);
            long modified = Files.getLastModifiedTime(file).toMillis();
            String content = Files.readString(file, StandardCharsets.UTF_8);
            return new NotesViews.FileView(rel, fileName(rel), size, modified, content);
        }
        catch (IOException e) {
            throw ioError("读取笔记失败：" + rel, e);
        }
    }

    /** 新建或整体覆盖一篇笔记（.md）。 */
    public NotesViews.SaveResult save(Long userId, String rel, String content) {
        requireNoteExtension(rel);
        byte[] bytes = (content == null ? "" : content).getBytes(StandardCharsets.UTF_8);
        if (bytes.length > MAX_NOTE_BYTES) {
            throw new ResponseStatusException(HttpStatus.PAYLOAD_TOO_LARGE,
                    "笔记超过大小上限（" + (MAX_NOTE_BYTES / 1024 / 1024) + " MiB）");
        }
        Path home = ensureHome(userId);
        Path file = guard(home, rel);
        if (Files.isDirectory(file)) {
            throw badRequest("「" + rel + "」已存在且是文件夹");
        }
        try {
            Path parent = file.getParent();
            if (!Files.isDirectory(parent)) {
                throw new ResponseStatusException(HttpStatus.NOT_FOUND,
                        "父目录不存在：" + display(parent, home));
            }
            Files.write(file, bytes,
                    StandardOpenOption.CREATE,
                    StandardOpenOption.TRUNCATE_EXISTING,
                    StandardOpenOption.WRITE);
            return new NotesViews.SaveResult(rel, Files.size(file),
                    Files.getLastModifiedTime(file).toMillis());
        }
        catch (IOException e) {
            throw ioError("保存笔记失败：" + rel, e);
        }
    }

    /** 删除一篇笔记（.md）。 */
    public void deleteFile(Long userId, String rel) {
        requireNoteExtension(rel);
        Path home = ensureHome(userId);
        Path file = guard(home, rel);
        if (!Files.exists(file)) {
            throw notFound("笔记不存在：" + rel);
        }
        if (Files.isDirectory(file)) {
            throw badRequest("「" + rel + "」是文件夹，请用目录删除");
        }
        try {
            Files.delete(file);
        }
        catch (IOException e) {
            throw ioError("删除笔记失败：" + rel, e);
        }
    }

    /** 递归新建文件夹（含父目录）。 */
    public void createDir(Long userId, String rel) {
        Path home = ensureHome(userId);
        Path dir = guard(home, rel);
        try {
            Files.createDirectories(dir);
        }
        catch (IOException e) {
            throw ioError("新建文件夹失败：" + rel, e);
        }
    }

    /** 递归删除文件夹。 */
    public void deleteDir(Long userId, String rel) {
        Path home = ensureHome(userId);
        Path dir = guard(home, rel);
        if (!Files.exists(dir)) {
            throw notFound("文件夹不存在：" + rel);
        }
        if (!Files.isDirectory(dir)) {
            throw badRequest("「" + rel + "」不是文件夹");
        }
        try (var walk = Files.walk(dir)) {
            List<Path> paths = walk.sorted(Comparator.reverseOrder()).toList();
            for (Path p : paths) {
                Files.deleteIfExists(p);
            }
        }
        catch (IOException e) {
            throw ioError("删除文件夹失败：" + rel, e);
        }
    }

    /** 重命名 / 移动笔记或文件夹。 */
    public void rename(Long userId, String from, String to) {
        if (from == null || to == null || from.isBlank() || to.isBlank()) {
            throw badRequest("重命名需要提供 from 与 to");
        }
        Path home = ensureHome(userId);
        Path source = guard(home, from);
        Path target = guard(home, to);
        if (!Files.exists(source)) {
            throw notFound("原路径不存在：" + from);
        }
        boolean sourceIsFile = !Files.isDirectory(source);
        if (sourceIsFile) {
            requireNoteExtension(from);
            requireNoteExtension(to);
        }
        else if (to.endsWith(".md")) {
            throw badRequest("文件夹不能命名为 .md 笔记文件");
        }
        if (from.equals(to)) {
            return;
        }
        if (Files.exists(target)) {
            throw new ResponseStatusException(HttpStatus.CONFLICT,
                    "目标位置已存在：" + to);
        }
        try {
            Path parent = target.getParent();
            if (parent != null && !Files.isDirectory(parent)) {
                Files.createDirectories(parent);
            }
            try {
                Files.move(source, target, StandardCopyOption.ATOMIC_MOVE);
            }
            catch (java.nio.file.AtomicMoveNotSupportedException e) {
                Files.move(source, target);
            }
        }
        catch (IOException e) {
            throw ioError("重命名失败：" + from + " → " + to, e);
        }
    }

    // ---------- 内部工具 ----------

    private Path ensureHome(Long userId) {
        Path home = homeDir(userId);
        try {
            Files.createDirectories(home);
        }
        catch (IOException e) {
            throw ioError("无法初始化笔记目录", e);
        }
        return home;
    }

    Path homeDir(Long userId) {
        if (userId == null) {
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "未登录");
        }
        Path root = Path.of(properties.getRoot()).toAbsolutePath().normalize();
        return root.resolve("user-" + userId);
    }

    private NotesViews.Node buildNode(Path dir, String name, String rel) throws IOException {
        List<NotesViews.Node> children = new ArrayList<>();
        try (var stream = Files.list(dir)) {
            List<Path> entries = stream
                    .filter(p -> !p.getFileName().toString().startsWith("."))
                    .filter(p -> !Files.isSymbolicLink(p))
                    .sorted(Comparator
                            .comparing((Path p) -> !Files.isDirectory(p))
                            .thenComparing(p -> p.getFileName().toString().toLowerCase()))
                    .toList();
            for (Path entry : entries) {
                String entryName = entry.getFileName().toString();
                String entryRel = rel.isEmpty() ? entryName : rel + "/" + entryName;
                if (Files.isDirectory(entry)) {
                    children.add(buildNode(entry, entryName, entryRel));
                }
                else if (entryName.toLowerCase().endsWith(".md")) {
                    children.add(new NotesViews.Node(entryName, entryRel, "file", List.of()));
                }
            }
        }
        return new NotesViews.Node(name, rel, "dir", children);
    }

    /**
     * 把相对路径解析到用户目录内并做防逃逸校验：
     * 拒绝绝对路径、{@code ..}、空段与非法控制字符；对已存在部分解析真实路径，
     * 防止经符号链接读写到用户目录之外。
     */
    private Path guard(Path home, String rel) {
        String cleaned = rel == null ? "" : rel.replace('\\', '/').trim();
        if (cleaned.startsWith("/")) {
            throw badRequest("不接受绝对路径：" + rel);
        }
        if (cleaned.isEmpty()) {
            throw badRequest("路径不能为空");
        }
        Path resolved = home;
        for (String seg : cleaned.split("/")) {
            if (seg.isEmpty() || seg.equals(".") || seg.equals("..")) {
                throw badRequest("非法路径：" + rel);
            }
            validateSegment(seg, rel);
            resolved = resolved.resolve(seg);
        }
        resolved = resolved.normalize();
        if (!resolved.startsWith(home.normalize())) {
            throw forbidden("路径越界：" + rel);
        }
        try {
            assertNoSymlinkEscape(home, resolved);
        }
        catch (IOException e) {
            throw ioError("校验笔记路径失败", e);
        }
        return resolved;
    }

    private void validateSegment(String seg, String rel) {
        for (int i = 0; i < seg.length(); i++) {
            char c = seg.charAt(i);
            if (c < 0x20 || c == 0x7F) {
                throw badRequest("路径包含非法字符：" + rel);
            }
        }
        if (seg.endsWith(".")) {
            throw badRequest("路径不能以点结尾：" + rel);
        }
    }

    private void assertNoSymlinkEscape(Path home, Path target) throws IOException {
        Path realHome = home.toRealPath();
        Path p = target;
        Deque<String> missing = new ArrayDeque<>();
        while (!Files.exists(p, LinkOption.NOFOLLOW_LINKS)) {
            Path parent = p.getParent();
            if (parent == null) {
                break;
            }
            missing.push(p.getFileName().toString());
            p = parent;
        }
        Path real = p.toRealPath();
        if (!real.startsWith(realHome)) {
            throw forbidden("路径超出笔记目录：" + target.getFileName());
        }
        if (missing.isEmpty()) {
            return;
        }
        Path verified = real;
        for (String seg : missing) {
            verified = verified.resolve(seg);
        }
        if (!verified.startsWith(realHome)) {
            throw forbidden("路径超出笔记目录");
        }
    }

    private void requireNoteExtension(String rel) {
        String lower = rel == null ? "" : rel.toLowerCase();
        if (!lower.endsWith(".md")) {
            throw badRequest("仅支持 .md 笔记文件：" + rel);
        }
    }

    private String fileName(String rel) {
        int idx = rel.lastIndexOf('/');
        return idx < 0 ? rel : rel.substring(idx + 1);
    }

    private String display(Path file, Path home) {
        return home.relativize(file).toString();
    }

    private ResponseStatusException badRequest(String message) {
        return new ResponseStatusException(HttpStatus.BAD_REQUEST, message);
    }

    private ResponseStatusException forbidden(String message) {
        return new ResponseStatusException(HttpStatus.FORBIDDEN, message);
    }

    private ResponseStatusException notFound(String message) {
        return new ResponseStatusException(HttpStatus.NOT_FOUND, message);
    }

    private ResponseStatusException ioError(String message, IOException cause) {
        return new ResponseStatusException(HttpStatus.INTERNAL_SERVER_ERROR, message, cause);
    }
}

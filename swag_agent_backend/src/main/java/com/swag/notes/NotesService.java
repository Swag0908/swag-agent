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
import java.util.UUID;

/**
 * Markdown 笔记的磁盘读写服务。
 * <p>
 * 笔记文件存放在服务器磁盘 {@code <app.notes.root>/user-<userId>}（按用户维度隔离）。
 * 对外全部使用相对路径（以 / 分隔，如 {@code 工作/周报.md}）。
 * <p>
 * 目录模型：
 * <ul>
 *   <li>{@code 未分类}：每个用户默认存在的文件夹，放"未分类"的散笔记（根目录新建/恢复降级/删文件夹平铺）；</li>
 *   <li>{@code .trash}：每用户的隐藏回收站，删除的笔记/文件夹先进这里，7 天后自动清除，
 *       可恢复（原目录仍在则放回原处，否则进「未分类」）。</li>
 * </ul>
 * 安全：相对路径解析 + 拒绝 {@code ..}、绝对路径、控制字符、以点开头的保留段（含 .trash），
 * 并对已存在部分校验真实路径防止符号链接逃逸。
 */
@Service
public class NotesService {

    /** 单个笔记文件大小上限（2 MiB）。 */
    private static final long MAX_NOTE_BYTES = 2L * 1024 * 1024;

    /** 默认"未分类"文件夹名。 */
    static final String UNCLASSIFIED = "未分类";

    /** 每用户隐藏回收站目录名（点开头，不进目录树）。 */
    static final String TRASH_DIR = ".trash";

    /** 回收站保留时长：7 天。 */
    private static final long RETENTION_MS = 7L * 24 * 3600 * 1000;

    private final NotesProperties properties;

    public NotesService(NotesProperties properties) {
        this.properties = properties;
    }

    // ---------- 常规操作 ----------

    /** 返回用户笔记目录的树（根为用户的专属目录，含默认「未分类」文件夹）。 */
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
        requireNoteExtension(rel);
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

    /** 新建或整体覆盖一篇笔记（.md）。父目录必须已存在。 */
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

    /** 重命名 / 移动笔记或文件夹。 */
    public void rename(Long userId, String from, String to) {
        if (from == null || to == null || from.isBlank() || to.isBlank()) {
            throw badRequest("重命名需要提供 from 与 to");
        }
        if (UNCLASSIFIED.equals(from)) {
            throw badRequest("「" + UNCLASSIFIED + "」是系统文件夹，不能改名");
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
            throw new ResponseStatusException(HttpStatus.CONFLICT, "目标位置已存在：" + to);
        }
        try {
            Path parent = target.getParent();
            if (parent != null && !Files.isDirectory(parent)) {
                Files.createDirectories(parent);
            }
            moveWithin(source, target);
        }
        catch (IOException e) {
            throw ioError("重命名失败：" + from + " → " + to, e);
        }
    }

    // ---------- 删除与回收站 ----------

    /**
     * 删除一篇笔记：移入该用户回收站（可恢复；7 天后自动清除）。
     */
    public void deleteFile(Long userId, String rel) {
        requireNoteExtension(rel);
        Path home = ensureHome(userId);
        Path file = guard(home, rel);
        if (!Files.exists(file)) {
            throw notFound("笔记不存在：" + rel);
        }
        if (Files.isDirectory(file)) {
            throw badRequest("「" + rel + "」是文件夹，请删除文件夹");
        }
        trashItem(home, file, rel, "file");
    }

    /**
     * 删除整个文件夹（含内容），整体移入回收站（可恢复）。
     */
    public void deleteDirToTrash(Long userId, String rel) {
        if (UNCLASSIFIED.equals(rel)) {
            throw badRequest("「" + UNCLASSIFIED + "」是系统文件夹，不能删除");
        }
        Path home = ensureHome(userId);
        Path dir = requireDir(home, rel);
        trashItem(home, dir, rel, "dir");
    }

    /**
     * 删除文件夹但保留笔记：文件夹下所有 .md 平铺移入「未分类」（重名自动加序号），
     * 然后删除原文件夹（含剩余非笔记文件）。
     */
    public void deleteDirFlatten(Long userId, String rel) {
        if (UNCLASSIFIED.equals(rel)) {
            throw badRequest("「" + UNCLASSIFIED + "」是系统文件夹，不能删除");
        }
        Path home = ensureHome(userId);
        Path dir = requireDir(home, rel);
        try {
            Path unclassified = ensureUnclassified(home);
            // 先把 .md 笔记逐一平铺到未分类（先记下再移，避免遍历中目录被改）
            List<String> mdFiles = new ArrayList<>();
            try (var walk = Files.walk(dir)) {
                for (Path p : walk.filter(Files::isRegularFile)
                        .filter(p -> p.getFileName().toString().toLowerCase().endsWith(".md"))
                        .sorted().toList()) {
                    mdFiles.add(display(p, home));
                }
            }
            for (String fileRel : mdFiles) {
                Path src = home.resolve(fileRel);
                String base = fileRel.substring(fileRel.lastIndexOf('/') + 1);
                Path target = uniqueTarget(unclassified, base);
                moveWithin(src, target);
            }
            // 清掉原文件夹剩余内容
            deleteTree(dir);
        }
        catch (IOException e) {
            throw ioError("删除文件夹（笔记移入未分类）失败：" + rel, e);
        }
    }

    /** 列出回收站条目（顺带清理已过期条目）。 */
    public List<NotesViews.TrashView> listTrash(Long userId) {
        Path home = homeDir(userId);
        try {
            purgeTrashHome(home);
            Path trash = home.resolve(TRASH_DIR);
            if (!Files.isDirectory(trash)) {
                return List.of();
            }
            List<NotesViews.TrashView> views = new ArrayList<>();
            try (var stream = Files.list(trash)) {
                for (Path entryDir : stream.sorted().toList()) {
                    if (!Files.isDirectory(entryDir)) continue;
                    EntryMeta meta = readEntryMeta(entryDir);
                    if (meta == null) {
                        continue;
                    }
                    Path data = entryData(entryDir, meta.kind());
                    if (!Files.exists(data)) {
                        // 数据丢失的坏条目静默清理
                        deleteTree(entryDir);
                        continue;
                    }
                    views.add(new NotesViews.TrashView(
                            entryDir.getFileName().toString(),
                            meta.originalPath(),
                            fileName(meta.originalPath()),
                            meta.kind(),
                            meta.deletedAt()));
                }
            }
            views.sort(Comparator.comparingLong(NotesViews.TrashView::deletedAt).reversed());
            return views;
        }
        catch (IOException e) {
            throw ioError("读取回收站失败", e);
        }
    }

    /**
     * 从回收站恢复：文件/文件夹尽量放回原路径；原目录已不存在则放入「未分类」。
     */
    public void restore(Long userId, String trashId) {
        Path home = ensureHome(userId);
        Path entryDir = requireTrashEntry(home, trashId);
        EntryMeta meta = readEntryMeta(entryDir);
        if (meta == null) {
            throw badRequest("回收站条目无效：" + trashId);
        }
        try {
            Path data = entryData(entryDir, meta.kind());
            if (!Files.exists(data)) {
                deleteTree(entryDir);
                throw notFound("回收站条目已失效（文件丢失）");
            }
            String original = meta.originalPath();
            Path target;
            if ("file".equals(meta.kind())) {
                target = pickRestoreTarget(home, original, false);
                moveWithin(data, target);
            }
            else {
                target = pickRestoreTarget(home, original, true);
                Files.createDirectories(target.getParent());
                moveWithin(data, target);
            }
            deleteTree(entryDir);
        }
        catch (IOException e) {
            throw ioError("恢复失败：" + trashId, e);
        }
    }

    /** 永久删除某条回收站记录。 */
    public void deleteTrashEntry(Long userId, String trashId) {
        Path home = homeDir(userId);
        Path entryDir = requireTrashEntry(home, trashId);
        try {
            deleteTree(entryDir);
        }
        catch (IOException e) {
            throw ioError("删除回收站条目失败", e);
        }
    }

    /** 清空回收站（全部永久删除）。 */
    public void clearTrash(Long userId) {
        Path home = homeDir(userId);
        try {
            purgeTrashHome(home);
            Path trash = home.resolve(TRASH_DIR);
            if (Files.isDirectory(trash)) {
                deleteTree(trash);
            }
        }
        catch (IOException e) {
            throw ioError("清空回收站失败", e);
        }
    }

    // ---------- 内部：回收站 ----------

    private record EntryMeta(String originalPath, String kind, long deletedAt) {
    }

    private void trashItem(Path home, Path source, String originalRel, String kind) {
        try {
            Path trash = Files.createDirectories(home.resolve(TRASH_DIR));
            String id = UUID.randomUUID().toString();
            Path entryDir = trash.resolve(id);
            Files.createDirectories(entryDir);
            // 先移动数据，再写元数据（数据已安全迁移到回收站目录）
            Path data = entryDir.resolve(kind.equals("file") ? "note.md" : "content");
            moveWithin(source, data);
            writeEntryMeta(entryDir, originalRel, kind);
        }
        catch (IOException e) {
            throw ioError("移入回收站失败：" + originalRel, e);
        }
    }

    private void writeEntryMeta(Path entryDir, String originalRel, String kind) throws IOException {
        long now = System.currentTimeMillis();
        String content = "originalPath=" + originalRel + "\n"
                + "kind=" + kind + "\n"
                + "deletedAt=" + now + "\n";
        Files.writeString(entryDir.resolve("entry.json"), content, StandardCharsets.UTF_8);
    }

    private EntryMeta readEntryMeta(Path entryDir) {
        try {
            Path metaFile = entryDir.resolve("entry.json");
            if (!Files.isRegularFile(metaFile)) {
                return null;
            }
            String originalPath = null;
            String kind = null;
            long deletedAt = 0;
            for (String line : Files.readAllLines(metaFile, StandardCharsets.UTF_8)) {
                int idx = line.indexOf('=');
                if (idx <= 0) continue;
                String key = line.substring(0, idx);
                String value = line.substring(idx + 1);
                if ("originalPath".equals(key)) originalPath = value;
                else if ("kind".equals(key)) kind = value;
                else if ("deletedAt".equals(key)) {
                    try {
                        deletedAt = Long.parseLong(value.trim());
                    }
                    catch (NumberFormatException ignored) {
                    }
                }
            }
            if (originalPath == null || originalPath.isBlank() || deletedAt <= 0) {
                return null;
            }
            if (!"file".equals(kind) && !"dir".equals(kind)) {
                return null;
            }
            return new EntryMeta(originalPath, kind, deletedAt);
        }
        catch (IOException e) {
            return null;
        }
    }

    private Path entryData(Path entryDir, String kind) {
        return entryDir.resolve(kind.equals("file") ? "note.md" : "content");
    }

    private Path requireTrashEntry(Path home, String trashId) {
        if (trashId == null || !trashId.matches("^[0-9A-Za-z-]{8,64}$")) {
            throw badRequest("回收站条目编号非法");
        }
        Path entryDir = home.resolve(TRASH_DIR).resolve(trashId).normalize();
        if (!entryDir.startsWith(home.resolve(TRASH_DIR).normalize())) {
            throw badRequest("回收站条目编号非法");
        }
        if (!Files.isDirectory(entryDir)) {
            throw notFound("回收站条目不存在：" + trashId);
        }
        return entryDir;
    }

    /**
     * 恢复目标：原目录仍在 → 原路径；否则文件进「未分类」根、文件夹放「未分类/<原名>」。
     */
    private Path pickRestoreTarget(Path home, String originalRel, boolean isDir) throws IOException {
        String name = fileName(originalRel);
        if (originalRel.contains("/")) {
            String parentRel = originalRel.substring(0, originalRel.lastIndexOf('/'));
            Path parent = home.resolve(parentRel);
            Path candidate = parent.resolve(name);
            if (Files.isDirectory(parent) && !Files.exists(candidate, LinkOption.NOFOLLOW_LINKS)) {
                return candidate;
            }
        }
        else {
            // 原文件本就在根目录：直接放回
            Path candidate = home.resolve(name);
            if (!Files.exists(candidate, LinkOption.NOFOLLOW_LINKS)) {
                return candidate;
            }
        }
        // 原目录不存在 / 目标被占用 → 未分类兜底
        Path unclassified = ensureUnclassified(home);
        if (isDir) {
            Path target = uniqueTarget(unclassified, name);
            return target;
        }
        return uniqueTarget(unclassified, name);
    }

    /** 在目标目录内找可用文件名（重名则加 " (n)"）。 */
    private Path uniqueTarget(Path dir, String name) throws IOException {
        Files.createDirectories(dir);
        Path candidate = dir.resolve(name);
        if (!Files.exists(candidate, LinkOption.NOFOLLOW_LINKS)) {
            return candidate;
        }
        int dot = name.lastIndexOf('.');
        String stem = dot > 0 ? name.substring(0, dot) : name;
        String ext = dot > 0 ? name.substring(dot) : "";
        for (int i = 1; ; i++) {
            candidate = dir.resolve(stem + " (" + i + ")" + ext);
            if (!Files.exists(candidate, LinkOption.NOFOLLOW_LINKS)) {
                return candidate;
            }
        }
    }

    /** 清理指定用户回收站中已过保留期的条目。 */
    void purgeTrashHome(Path home) throws IOException {
        Path trash = home.resolve(TRASH_DIR);
        if (!Files.isDirectory(trash)) {
            return;
        }
        long cutoff = System.currentTimeMillis() - RETENTION_MS;
        try (var stream = Files.list(trash)) {
            for (Path entryDir : stream.toList()) {
                if (!Files.isDirectory(entryDir)) continue;
                EntryMeta meta = readEntryMeta(entryDir);
                if (meta == null || meta.deletedAt() < cutoff) {
                    deleteTree(entryDir);
                }
            }
        }
    }

    /** 清理所有用户的过期回收站（供定时任务）。 */
    public void purgeAllExpired() {
        Path root = Path.of(properties.getRoot()).toAbsolutePath().normalize();
        if (!Files.isDirectory(root)) {
            return;
        }
        try (var stream = Files.list(root)) {
            for (Path child : stream.toList()) {
                if (Files.isDirectory(child) && child.getFileName().toString().startsWith("user-")) {
                    purgeTrashHome(child);
                }
            }
        }
        catch (IOException e) {
            // 定时清理失败不阻断主流程，记录日志即可
            throw ioError("回收站定时清理失败", e);
        }
    }

    // ---------- 内部工具 ----------

    private Path ensureHome(Long userId) {
        Path home = homeDir(userId);
        try {
            Files.createDirectories(home);
            Files.createDirectories(home.resolve(UNCLASSIFIED));
        }
        catch (IOException e) {
            throw ioError("无法初始化笔记目录", e);
        }
        return home;
    }

    private Path ensureUnclassified(Path home) throws IOException {
        return Files.createDirectories(home.resolve(UNCLASSIFIED));
    }

    private Path requireDir(Path home, String rel) {
        Path dir = guard(home, rel);
        if (!Files.exists(dir)) {
            throw notFound("文件夹不存在：" + rel);
        }
        if (!Files.isDirectory(dir)) {
            throw badRequest("「" + rel + "」不是文件夹");
        }
        return dir;
    }

    private void moveWithin(Path source, Path target) throws IOException {
        Path parent = target.getParent();
        if (parent != null) {
            Files.createDirectories(parent);
        }
        try {
            Files.move(source, target, StandardCopyOption.ATOMIC_MOVE);
        }
        catch (java.nio.file.AtomicMoveNotSupportedException e) {
            Files.move(source, target);
        }
    }

    private void deleteTree(Path dir) throws IOException {
        if (!Files.exists(dir, LinkOption.NOFOLLOW_LINKS)) {
            return;
        }
        try (var walk = Files.walk(dir)) {
            List<Path> paths = walk.sorted(Comparator.reverseOrder()).toList();
            for (Path p : paths) {
                Files.deleteIfExists(p);
            }
        }
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
     * 拒绝绝对路径、{@code ..}、空段、控制字符与以点开头的保留段（.trash 等隐藏项）；
     * 对已存在部分解析真实路径，防止经符号链接读写到用户目录之外。
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
            if (seg.isEmpty() || seg.equals(".") || seg.equals("..") || seg.startsWith(".")) {
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
        int idx = rel == null ? -1 : rel.lastIndexOf('/');
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

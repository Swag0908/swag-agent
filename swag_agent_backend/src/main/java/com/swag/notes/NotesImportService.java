package com.swag.notes;

import org.springframework.core.io.FileSystemResource;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.web.multipart.MultipartFile;
import org.springframework.web.server.ResponseStatusException;

import java.io.IOException;
import java.net.URLDecoder;
import java.net.URLEncoder;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.LinkOption;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.UUID;
import java.util.function.Function;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Markdown 笔记导入边界：统一处理服务器本地路径、浏览器上传、附件发现与链接改写。
 * 调用方只需提供来源和目标文件夹，不需要了解允许目录、重名、资源存储或 URL 规则。
 */
@Service
public class NotesImportService {

    private static final String RESOURCE_DIR = ".resources";

    /** Markdown 行内链接/图片。路径里有空格时应使用 &lt;...&gt; 或 URL 编码。 */
    private static final Pattern INLINE_LINK = Pattern.compile(
            "(!?\\[[^\\r\\n]*?]\\(\\s*)(<[^>\\r\\n]+>|[^\\s)]+)([^\\r\\n)]*\\))");
    /** Markdown 引用式链接定义：[id]: path "title"。 */
    private static final Pattern REFERENCE_LINK = Pattern.compile(
            "(?m)^(\\s{0,3}\\[[^\\r\\n]+]:\\s*)(<[^>\\r\\n]+>|\\S+)(.*)$");
    /** Markdown 中的原生 HTML 资源属性；脚本内容不会执行，前端仍会经过 DOMPurify。 */
    private static final Pattern HTML_LINK = Pattern.compile(
            "(?i)(\\b(?:src|href)\\s*=\\s*[\"'])([^\"']+)([\"'])");
    /** Obsidian 常见的附件语法。 */
    private static final Pattern WIKI_EMBED = Pattern.compile(
            "(!\\[\\[)([^|\\]\\r\\n]+)([^\\]\\r\\n]*]])");

    private final NotesService notesService;
    private final NotesProperties properties;

    public NotesImportService(NotesService notesService, NotesProperties properties) {
        this.notesService = notesService;
        this.properties = properties;
    }

    public NotesViews.ImportConfig config() {
        return new NotesViews.ImportConfig(properties.getImportRoots().stream()
                .filter(root -> root != null && !root.isBlank())
                .map(String::strip)
                .toList());
    }

    /** 上传项的相对路径由浏览器提供；选择普通文件时就是文件名，选择文件夹时包含目录层级。 */
    public record UploadPart(String relativePath, MultipartFile file) {
    }

    /** 从启动后端的机器上批量导入绝对路径。 */
    public NotesViews.ImportResult importLocal(Long userId, List<String> sourcePaths, String targetDir) {
        List<String> requested = sourcePaths == null ? List.of() : sourcePaths.stream()
                .filter(path -> path != null && !path.isBlank())
                .map(String::strip)
                .toList();
        if (requested.isEmpty()) {
            throw badRequest("请至少提供一个 .md 文件路径");
        }

        BatchResult batch = new BatchResult();
        BatchBudget budget = new BatchBudget(properties.getMaxImportTotalBytes());
        List<Path> roots = importRoots();
        for (String sourceText : requested) {
            Path bundle = null;
            try {
                Path source = allowedLocalFile(Path.of(sourceText), roots, true);
                long size = Files.size(source);
                requireMarkdownSize(size, sourceText);
                budget.add(size);
                String markdown = new String(Files.readAllBytes(source), StandardCharsets.UTF_8);

                ResourceBundle resources = new ResourceBundle(userId, budget, batch.warnings);
                bundle = resources.directory;
                String rewritten = rewriteLinks(markdown, target ->
                        importLocalAttachment(source, target, roots, resources, sourceText));
                NotesViews.SaveResult saved = notesService.createUnique(
                        userId, normalizedTargetDir(targetDir), source.getFileName().toString(), rewritten);
                resources.removeIfEmpty();
                batch.imported.add(saved.path());
                batch.attachmentsCopied += resources.copiedCount;
            }
            catch (Exception e) {
                deleteQuietly(bundle);
                batch.failed.add(new NotesViews.ImportFailure(sourceText, reason(e)));
            }
        }
        return batch.view();
    }

    /**
     * 导入浏览器选择的文件。普通多选可导入多篇 Markdown；选择文件夹时，其它上传项会作为
     * Markdown 可解析的附件源，未被引用的文件不会写入笔记资源目录。
     */
    public NotesViews.ImportResult importUploads(Long userId, List<UploadPart> parts, String targetDir) {
        if (parts == null || parts.isEmpty()) {
            throw badRequest("请选择要导入的文件");
        }
        Map<String, MultipartFile> files = new LinkedHashMap<>();
        for (UploadPart part : parts) {
            if (part == null || part.file() == null) {
                continue;
            }
            String relative = normalizeUploadPath(part.relativePath(), part.file().getOriginalFilename());
            if (files.putIfAbsent(relative, part.file()) != null) {
                throw badRequest("上传内容包含重复路径：" + relative);
            }
        }
        List<String> markdownPaths = files.keySet().stream()
                .filter(NotesImportService::isMarkdown)
                .toList();
        if (markdownPaths.isEmpty()) {
            throw badRequest("所选内容中没有 .md 文件");
        }

        BatchResult batch = new BatchResult();
        BatchBudget budget = new BatchBudget(properties.getMaxImportTotalBytes());
        for (String markdownPath : markdownPaths) {
            Path bundle = null;
            try {
                MultipartFile markdownFile = files.get(markdownPath);
                requireMarkdownSize(markdownFile.getSize(), markdownPath);
                budget.add(markdownFile.getSize());
                String markdown = new String(markdownFile.getBytes(), StandardCharsets.UTF_8);

                ResourceBundle resources = new ResourceBundle(userId, budget, batch.warnings);
                bundle = resources.directory;
                String rewritten = rewriteLinks(markdown, target ->
                        importUploadedAttachment(markdownPath, target, files, resources));
                NotesViews.SaveResult saved = notesService.createUnique(
                        userId, normalizedTargetDir(targetDir), fileName(markdownPath), rewritten);
                resources.removeIfEmpty();
                batch.imported.add(saved.path());
                batch.attachmentsCopied += resources.copiedCount;
            }
            catch (Exception e) {
                deleteQuietly(bundle);
                batch.failed.add(new NotesViews.ImportFailure(markdownPath, reason(e)));
            }
        }
        return batch.view();
    }

    /** 当前登录用户导入附件的受控读取入口。 */
    public NotesViews.ResourceView resource(Long userId, String bundleId, String name) {
        if (bundleId == null || !bundleId.matches("[0-9a-fA-F-]{36}")) {
            throw badRequest("资源编号非法");
        }
        if (name == null || name.isBlank() || name.contains("/") || name.contains("\\")
                || name.equals(".") || name.equals("..")) {
            throw badRequest("资源名称非法");
        }
        Path root = notesService.homeDir(userId).resolve(RESOURCE_DIR).resolve(bundleId).normalize();
        Path file = root.resolve(name).normalize();
        if (!file.startsWith(root) || !Files.isRegularFile(file, LinkOption.NOFOLLOW_LINKS)) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "导入资源不存在");
        }
        try {
            Path realRoot = root.toRealPath();
            Path realFile = file.toRealPath();
            if (!realFile.startsWith(realRoot)) {
                throw new ResponseStatusException(HttpStatus.FORBIDDEN, "资源路径越界");
            }
            String contentType = Files.probeContentType(realFile);
            if (contentType == null || contentType.isBlank()) {
                contentType = "application/octet-stream";
            }
            String lower = name.toLowerCase(Locale.ROOT);
            boolean inline = lower.endsWith(".png") || lower.endsWith(".jpg")
                    || lower.endsWith(".jpeg") || lower.endsWith(".gif")
                    || lower.endsWith(".webp") || lower.endsWith(".avif");
            return new NotesViews.ResourceView(
                    new FileSystemResource(realFile), name, contentType, inline);
        }
        catch (IOException e) {
            throw new ResponseStatusException(HttpStatus.INTERNAL_SERVER_ERROR, "读取导入资源失败", e);
        }
    }

    private String importLocalAttachment(Path markdown, String rawTarget, List<Path> roots,
                                         ResourceBundle resources, String sourceLabel) {
        LinkTarget target = LinkTarget.parse(rawTarget);
        if (target == null) {
            return null;
        }
        try {
            Path requested = Path.of(target.decodedPath());
            Path candidate = requested.isAbsolute()
                    ? requested
                    : markdown.getParent().resolve(requested);
            Path attachment = allowedLocalFile(candidate, roots, false);
            String url = resources.copyLocal(attachment);
            return url + target.suffix();
        }
        catch (Exception e) {
            resources.warn("「" + sourceLabel + "」未复制附件 " + rawTarget + "：" + reason(e));
            return null;
        }
    }

    private String importUploadedAttachment(String markdownPath, String rawTarget,
                                            Map<String, MultipartFile> files,
                                            ResourceBundle resources) {
        LinkTarget target = LinkTarget.parse(rawTarget);
        if (target == null) {
            return null;
        }
        if (target.decodedPath().startsWith("/") || Path.of(target.decodedPath()).isAbsolute()) {
            resources.warn("「" + markdownPath + "」中的绝对附件路径无法通过浏览器上传解析：" + rawTarget);
            return null;
        }
        try {
            String base = parentOf(markdownPath);
            String candidate = normalizeRelative(base.isEmpty()
                    ? target.decodedPath()
                    : base + "/" + target.decodedPath());
            MultipartFile attachment = files.get(candidate);
            if (attachment == null) {
                resources.warn("「" + markdownPath + "」缺少所引用的上传附件：" + rawTarget
                        + "（选择包含附件的文件夹即可一并导入）");
                return null;
            }
            String url = resources.copyUpload(candidate, attachment);
            return url + target.suffix();
        }
        catch (Exception e) {
            resources.warn("「" + markdownPath + "」未复制附件 " + rawTarget + "：" + reason(e));
            return null;
        }
    }

    private String rewriteLinks(String markdown, Function<String, String> importer) {
        String rewritten = replaceTargets(markdown, INLINE_LINK, 2, importer);
        rewritten = replaceTargets(rewritten, REFERENCE_LINK, 2, importer);
        rewritten = replaceTargets(rewritten, HTML_LINK, 2, importer);
        return replaceTargets(rewritten, WIKI_EMBED, 2, importer);
    }

    private String replaceTargets(String input, Pattern pattern, int targetGroup,
                                  Function<String, String> importer) {
        Matcher matcher = pattern.matcher(input);
        StringBuffer out = new StringBuffer();
        while (matcher.find()) {
            String raw = matcher.group(targetGroup);
            boolean angled = raw.startsWith("<") && raw.endsWith(">");
            String plain = angled ? raw.substring(1, raw.length() - 1) : raw;
            String replacement = importer.apply(plain);
            if (replacement == null) {
                matcher.appendReplacement(out, Matcher.quoteReplacement(matcher.group()));
                continue;
            }
            String finalTarget = angled ? "<" + replacement + ">" : replacement;
            String whole = matcher.group();
            int relativeStart = matcher.start(targetGroup) - matcher.start();
            String replaced = whole.substring(0, relativeStart) + finalTarget
                    + whole.substring(relativeStart + raw.length());
            matcher.appendReplacement(out, Matcher.quoteReplacement(replaced));
        }
        matcher.appendTail(out);
        return out.toString();
    }

    private List<Path> importRoots() {
        List<Path> roots = new ArrayList<>();
        for (String configured : properties.getImportRoots()) {
            if (configured == null || configured.isBlank()) {
                continue;
            }
            try {
                Path root = Path.of(configured.strip()).toAbsolutePath().normalize().toRealPath();
                if (Files.isDirectory(root)) {
                    roots.add(root);
                }
            }
            catch (IOException ignored) {
                // 配错或暂时不存在的根目录不扩大权限；所有根都不可用时导入会给出明确提示。
            }
        }
        if (roots.isEmpty()) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN,
                    "本地路径导入未配置可读取目录（app.notes.import-roots）");
        }
        return roots;
    }

    private Path allowedLocalFile(Path requested, List<Path> roots, boolean markdown) throws IOException {
        if (!requested.isAbsolute()) {
            throw badRequest("本地导入必须使用绝对路径：" + requested);
        }
        Path real = requested.normalize().toRealPath();
        if (roots.stream().noneMatch(real::startsWith)) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN,
                    "路径不在允许导入的目录内：" + requested);
        }
        if (!Files.isRegularFile(real, LinkOption.NOFOLLOW_LINKS)) {
            throw badRequest("不是普通文件：" + requested);
        }
        if (markdown && !isMarkdown(real.getFileName().toString())) {
            throw badRequest("仅支持导入 .md 文件：" + requested);
        }
        return real;
    }

    private void requireMarkdownSize(long size, String source) {
        if (size > properties.getMaxImportMarkdownBytes()) {
            throw new ResponseStatusException(HttpStatus.PAYLOAD_TOO_LARGE,
                    "Markdown 文件超过导入上限：" + source);
        }
    }

    private String normalizedTargetDir(String targetDir) {
        return targetDir == null || targetDir.isBlank() ? NotesService.UNCLASSIFIED : targetDir.strip();
    }

    private static String normalizeUploadPath(String supplied, String fallback) {
        String value = supplied == null || supplied.isBlank() ? fallback : supplied;
        if (value == null || value.isBlank()) {
            throw badRequest("上传文件缺少文件名");
        }
        return normalizeRelative(value);
    }

    private static String normalizeRelative(String value) {
        String slash = value.replace('\\', '/').strip();
        if (slash.startsWith("/") || slash.matches("^[A-Za-z]:/.*")) {
            throw badRequest("上传相对路径非法：" + value);
        }
        Path normalized = Path.of(slash).normalize();
        String result = normalized.toString().replace('\\', '/');
        if (result.isBlank() || result.equals(".") || result.equals("..") || result.startsWith("../")) {
            throw badRequest("上传相对路径非法：" + value);
        }
        return result;
    }

    private static boolean isMarkdown(String path) {
        return path != null && path.toLowerCase(Locale.ROOT).endsWith(".md");
    }

    private static String parentOf(String path) {
        int slash = path.lastIndexOf('/');
        return slash < 0 ? "" : path.substring(0, slash);
    }

    private static String fileName(String path) {
        int slash = path.lastIndexOf('/');
        return slash < 0 ? path : path.substring(slash + 1);
    }

    private static String safeResourceName(String path) {
        String name = fileName(path).replaceAll("[\\x00-\\x1F\\x7F/\\\\]", "_");
        return name.isBlank() ? "attachment" : name;
    }

    private static String reason(Exception exception) {
        if (exception instanceof ResponseStatusException response && response.getReason() != null) {
            return response.getReason();
        }
        String message = exception.getMessage();
        return message == null || message.isBlank() ? exception.getClass().getSimpleName() : message;
    }

    private static ResponseStatusException badRequest(String message) {
        return new ResponseStatusException(HttpStatus.BAD_REQUEST, message);
    }

    private static void deleteQuietly(Path path) {
        if (path == null || !Files.exists(path, LinkOption.NOFOLLOW_LINKS)) {
            return;
        }
        try (var walk = Files.walk(path)) {
            for (Path item : walk.sorted(java.util.Comparator.reverseOrder()).toList()) {
                Files.deleteIfExists(item);
            }
        }
        catch (IOException ignored) {
        }
    }

    private final class ResourceBundle {
        private final UUID id = UUID.randomUUID();
        private final Path directory;
        private final BatchBudget budget;
        private final List<String> warnings;
        private final Map<String, String> copied = new HashMap<>();
        private int copiedCount;

        private ResourceBundle(Long userId, BatchBudget budget, List<String> warnings) throws IOException {
            this.directory = notesService.homeDir(userId)
                    .resolve(RESOURCE_DIR).resolve(id.toString()).normalize();
            this.budget = budget;
            this.warnings = warnings;
            Files.createDirectories(directory);
        }

        private String copyLocal(Path source) throws IOException {
            String key = source.toString();
            String existing = copied.get(key);
            if (existing != null) {
                return existing;
            }
            long size = Files.size(source);
            requireAttachmentSize(size, source.toString());
            budget.add(size);
            Path target = uniqueResource(safeResourceName(source.getFileName().toString()));
            Files.copy(source, target, StandardCopyOption.COPY_ATTRIBUTES);
            return remember(key, target.getFileName().toString());
        }

        private String copyUpload(String relativePath, MultipartFile source) throws IOException {
            String existing = copied.get(relativePath);
            if (existing != null) {
                return existing;
            }
            requireAttachmentSize(source.getSize(), relativePath);
            budget.add(source.getSize());
            Path target = uniqueResource(safeResourceName(relativePath));
            try (var in = source.getInputStream()) {
                Files.copy(in, target);
            }
            return remember(relativePath, target.getFileName().toString());
        }

        private void requireAttachmentSize(long size, String source) {
            if (size > properties.getMaxImportAttachmentBytes()) {
                throw new ResponseStatusException(HttpStatus.PAYLOAD_TOO_LARGE,
                        "附件超过导入上限：" + source);
            }
        }

        private Path uniqueResource(String name) {
            Path candidate = directory.resolve(name);
            int dot = name.lastIndexOf('.');
            String stem = dot > 0 ? name.substring(0, dot) : name;
            String ext = dot > 0 ? name.substring(dot) : "";
            for (int i = 1; Files.exists(candidate, LinkOption.NOFOLLOW_LINKS); i++) {
                candidate = directory.resolve(stem + " (" + i + ")" + ext);
            }
            return candidate;
        }

        private String remember(String key, String name) {
            String encoded = URLEncoder.encode(name, StandardCharsets.UTF_8).replace("+", "%20");
            String url = "/api/notes/resource?bundle=" + id + "&name=" + encoded;
            copied.put(key, url);
            copiedCount++;
            return url;
        }

        private void warn(String warning) {
            warnings.add(warning);
        }

        private void removeIfEmpty() {
            if (copiedCount == 0) {
                deleteQuietly(directory);
            }
        }
    }

    private static final class BatchBudget {
        private final long maxBytes;
        private long usedBytes;

        private BatchBudget(long maxBytes) {
            this.maxBytes = maxBytes;
        }

        private void add(long bytes) {
            if (bytes < 0 || usedBytes > maxBytes - bytes) {
                throw new ResponseStatusException(HttpStatus.PAYLOAD_TOO_LARGE,
                        "本次批量导入超过总量上限（" + maxBytes + " 字节）");
            }
            usedBytes += bytes;
        }
    }

    private static final class BatchResult {
        private final List<String> imported = new ArrayList<>();
        private final List<NotesViews.ImportFailure> failed = new ArrayList<>();
        private final List<String> warnings = new ArrayList<>();
        private int attachmentsCopied;

        private NotesViews.ImportResult view() {
            return new NotesViews.ImportResult(
                    List.copyOf(imported), List.copyOf(failed), List.copyOf(warnings), attachmentsCopied);
        }
    }

    /** 本地链接去掉 URL 查询/锚点后用于找文件，复制后再把后缀接回去。 */
    private record LinkTarget(String decodedPath, String suffix) {
        private static LinkTarget parse(String raw) {
            if (raw == null || raw.isBlank()) {
                return null;
            }
            String value = raw.strip();
            String lower = value.toLowerCase(Locale.ROOT);
            if (value.startsWith("#") || value.startsWith("//")
                    || lower.startsWith("http:") || lower.startsWith("https:")
                    || lower.startsWith("data:") || lower.startsWith("mailto:")
                    || lower.startsWith("tel:") || lower.startsWith("javascript:")) {
                return null;
            }
            int suffixAt = value.length();
            int query = value.indexOf('?');
            int fragment = value.indexOf('#');
            if (query >= 0) suffixAt = Math.min(suffixAt, query);
            if (fragment >= 0) suffixAt = Math.min(suffixAt, fragment);
            String path = value.substring(0, suffixAt);
            if (path.isBlank()) {
                return null;
            }
            try {
                if (path.toLowerCase(Locale.ROOT).startsWith("file:")) {
                    return new LinkTarget(Path.of(URI.create(path)).toString(), value.substring(suffixAt));
                }
                return new LinkTarget(
                        URLDecoder.decode(path.replace("+", "%2B"), StandardCharsets.UTF_8),
                        value.substring(suffixAt));
            }
            catch (IllegalArgumentException e) {
                return new LinkTarget(path, value.substring(suffixAt));
            }
        }
    }
}

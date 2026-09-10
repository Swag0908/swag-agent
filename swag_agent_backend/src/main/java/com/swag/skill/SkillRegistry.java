package com.swag.skill;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.core.io.Resource;
import org.springframework.core.io.support.PathMatchingResourcePatternResolver;
import org.springframework.core.io.support.ResourcePatternResolver;
import org.springframework.stereotype.Component;

import java.io.IOException;
import java.io.InputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.attribute.FileTime;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.Optional;
import java.util.Set;
import java.util.stream.Stream;

/**
 * 技能注册表：扫描「内置 + 外部」两个根目录，解析每个 {@code SKILL.md}，并对外提供
 * 启用列表与启停控制。
 * <p>
 * 设计要点：
 * <ul>
 *     <li><b>放置即生效</b>：外部目录的 mtime 变化会在下次读取时触发重扫，所以"往目录里拷一个技能
 *     文件夹"或管理端安装完成后，无需重启、无需手动刷新即可进入下一轮对话；</li>
 *     <li><b>外部覆盖内置</b>：同名技能以外部目录版本为准，便于在不改代码、不发版的前提下覆盖；</li>
 *     <li><b>启停落库</b>：启用/停用状态存 {@code skill_state} 表（见 {@link SkillStateStore}），
 *     进程重启、多实例部署后依然保持；表里没有的技能默认启用；</li>
 *     <li><b>只读文本</b>：这里只读取 SKILL.md 正文，技能目录里的脚本/资源一律不执行。</li>
 * </ul>
 */
@Component
public class SkillRegistry {

    private static final Logger log = LoggerFactory.getLogger(SkillRegistry.class);

    /** 内置技能扫描位置：{@code src/main/resources/skills/<name>/SKILL.md}。 */
    private static final String CLASSPATH_PATTERN = "classpath*:skills/*/SKILL.md";

    private final SkillProperties properties;
    private final ResourcePatternResolver resourceResolver;
    private final SkillStateStore stateStore;

    /** 技能名 -> 清单（保持插入顺序，返回时按名称排序）。 */
    private final Map<String, SkillManifest> manifests = new LinkedHashMap<>();

    /** 上次扫描时外部目录的 mtime，用于判断目录内容是否变过。 */
    private FileTime externalStamp;

    private boolean scanned;

    @Autowired
    public SkillRegistry(SkillProperties properties, SkillStateStore stateStore) {
        this(properties, new PathMatchingResourcePatternResolver(), stateStore);
    }

    SkillRegistry(SkillProperties properties, ResourcePatternResolver resourceResolver, SkillStateStore stateStore) {
        this.properties = properties;
        this.resourceResolver = resourceResolver;
        this.stateStore = stateStore;
    }

    /** 全部技能（含停用的），按名称排序。 */
    public synchronized List<SkillManifest> list() {
        refreshIfChanged();
        return manifests.values().stream()
                .sorted(Comparator.comparing(SkillManifest::name))
                .toList();
    }

    /** 启用中的技能，按名称排序；注入 system prompt 用的就是这批。 */
    public synchronized List<SkillManifest> enabled() {
        Set<String> disabled = stateStore.disabledSkills();
        return list().stream()
                .filter(manifest -> !disabled.contains(manifest.name()))
                .toList();
    }

    public synchronized Optional<SkillManifest> find(String name) {
        refreshIfChanged();
        return Optional.ofNullable(manifests.get(name));
    }

    public synchronized boolean isEnabled(String name) {
        refreshIfChanged();
        return manifests.containsKey(name) && !stateStore.disabledSkills().contains(name);
    }

    /** 启停一个已发现的技能并落库；技能不存在返回 false。下一条消息即按新状态注入。 */
    public synchronized boolean setEnabled(String name, boolean enabled) {
        refreshIfChanged();
        if (!manifests.containsKey(name)) {
            return false;
        }
        stateStore.setEnabled(name, enabled);
        return true;
    }

    /** 删除一个外部技能目录（内置技能不可删）；不存在或为内置返回 false。 */
    public synchronized boolean deleteExternal(String name) {
        refreshIfChanged();
        SkillManifest manifest = manifests.get(name);
        if (manifest == null || !manifest.external()) {
            return false;
        }
        Path root = externalRoot();
        Path file = Path.of(manifest.filePath()).toAbsolutePath().normalize();
        Path dir = file.getParent();
        if (dir == null || !dir.startsWith(root)) {
            return false;
        }
        try {
            deleteRecursively(dir);
        } catch (IOException e) {
            throw new IllegalStateException("删除技能目录失败：" + dir, e);
        }
        stateStore.remove(name);
        refresh();
        return true;
    }

    /** 外部技能根目录（绝对路径）。安装技能就是往它下面写 {@code <name>/SKILL.md}。 */
    public Path externalRoot() {
        return Path.of(properties.getExternalRoot()).toAbsolutePath().normalize();
    }

    /** 重新扫描两个根目录；安装/手工拷贝完成后调用。 */
    public synchronized void refresh() {
        Map<String, SkillManifest> scannedManifests = new LinkedHashMap<>();
        List<SkillManifest> builtin = scanClasspath();
        List<SkillManifest> external = scanExternal();
        builtin.forEach(manifest -> scannedManifests.put(manifest.name(), manifest));
        // 外部同名覆盖内置
        external.forEach(manifest -> scannedManifests.put(manifest.name(), manifest));

        manifests.clear();
        manifests.putAll(scannedManifests);
        // 已被删除的技能不再保留历史启停状态（技能列表非空时才清理，避免扫描异常时误删设置）
        stateStore.removeMissing(manifests.keySet());
        externalStamp = currentExternalStamp();
        scanned = true;
        log.info("技能注册表刷新完成：共 {} 个（内置 {} / 外部 {}）",
                manifests.size(), builtin.size(), external.size());
    }

    /** 外部目录 mtime 变了（新增/删除技能目录）或尚未扫描过时重扫。 */
    private void refreshIfChanged() {
        FileTime current = currentExternalStamp();
        if (!scanned || !Objects.equals(current, externalStamp)) {
            refresh();
        }
    }

    private FileTime currentExternalStamp() {
        Path root = externalRoot();
        try {
            return Files.isDirectory(root) ? Files.getLastModifiedTime(root) : null;
        } catch (IOException e) {
            return null;
        }
    }

    private List<SkillManifest> scanClasspath() {
        List<SkillManifest> found = new ArrayList<>();
        try {
            for (Resource resource : resourceResolver.getResources(CLASSPATH_PATTERN)) {
                String filePath = describe(resource);
                try (InputStream in = resource.getInputStream()) {
                    String raw = new String(in.readAllBytes(), StandardCharsets.UTF_8);
                    parse(folderNameOf(resource), raw, filePath)
                            .ifPresent(parsed -> found.add(new SkillManifest(
                                    parsed.name(), parsed.description(), parsed.body(), false, filePath)));
                } catch (IOException e) {
                    log.warn("读取内置技能失败：{}（{}）", filePath, e.toString());
                }
            }
        } catch (IOException e) {
            log.warn("扫描内置技能目录失败（{}）：{}", CLASSPATH_PATTERN, e.toString());
        }
        return found;
    }

    private List<SkillManifest> scanExternal() {
        Path root = externalRoot();
        if (!Files.isDirectory(root)) {
            return List.of();
        }
        List<SkillManifest> found = new ArrayList<>();
        try (Stream<Path> children = Files.list(root)) {
            children.filter(Files::isDirectory)
                    .filter(dir -> !dir.getFileName().toString().startsWith("."))
                    .sorted()
                    .forEach(dir -> {
                        Path file = dir.resolve("SKILL.md");
                        if (!Files.isRegularFile(file)) {
                            return;
                        }
                        try {
                            String raw = Files.readString(file, StandardCharsets.UTF_8);
                            parse(dir.getFileName().toString(), raw, file.toString())
                                    .ifPresent(parsed -> found.add(new SkillManifest(
                                            parsed.name(), parsed.description(), parsed.body(), true, file.toString())));
                        } catch (IOException e) {
                            log.warn("读取外部技能失败：{}（{}）", file, e.toString());
                        }
                    });
        } catch (IOException e) {
            log.warn("扫描外部技能目录失败：{}（{}）", root, e.toString());
        }
        return found;
    }

    private Optional<SkillMarkdown.Parsed> parse(String folderName, String raw, String filePath) {
        SkillMarkdown.Result result = SkillMarkdown.parse(folderName, raw);
        if (!result.ok()) {
            log.warn("跳过无效技能 {}：{}", filePath, result.error());
            return Optional.empty();
        }
        return Optional.of(result.parsed());
    }

    /** 从技能文件路径推断技能目录名（frontmatter 未写 name 时的兜底）。 */
    private static String folderNameOf(Resource resource) {
        String path = null;
        try {
            path = resource.getURI().getPath();
        } catch (Exception ignored) {
            // 部分 Resource 实现没有可用 URI，退回描述串
        }
        if (path == null || path.isBlank()) {
            path = resource.getDescription();
        }
        String[] segments = path.replace('\\', '/').split("/");
        for (int i = segments.length - 1; i > 0; i--) {
            if ("SKILL.md".equalsIgnoreCase(segments[i])) {
                return segments[i - 1];
            }
        }
        return "";
    }

    private static String describe(Resource resource) {
        try {
            return resource.getURI().toString();
        } catch (Exception e) {
            return resource.getDescription();
        }
    }

    private static void deleteRecursively(Path path) throws IOException {
        if (!Files.exists(path)) {
            return;
        }
        try (Stream<Path> walk = Files.walk(path)) {
            for (Path item : walk.sorted(Comparator.reverseOrder()).toList()) {
                Files.deleteIfExists(item);
            }
        }
    }
}

package com.swag.skill;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Component;
import org.springframework.web.server.ResponseStatusException;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardCopyOption;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.List;
import java.util.concurrent.TimeUnit;
import java.util.regex.Pattern;
import java.util.stream.Stream;

/**
 * 技能安装器：把 Git 仓库里的技能目录拷进外部技能根目录，从而"从网上装技能"而无需为每个技能写 Java。
 * <p>
 * 支持三种仓库地址：GitHub 简写 {@code owner/repo}、{@code https://...}、{@code git@...}。
 * 安装过程在临时目录 clone（{@code --depth 1}），只拷贝技能目录本身，不保留 {@code .git}，
 * 也不会执行仓库中的任何脚本。技能自带脚本属于"可执行能力"，应走工具（@Tool / MCP）而非技能机制。
 */
@Component
public class SkillInstaller {

    private static final Logger log = LoggerFactory.getLogger(SkillInstaller.class);

    /** GitHub 简写 owner/repo。 */
    private static final Pattern SHORTHAND = Pattern.compile("[A-Za-z0-9][\\w.-]*/[\\w.-]+");

    /** 失败提示里搜索可选技能路径的最大深度（如 skills/<name>/SKILL.md 为 2 层）。 */
    private static final int CANDIDATE_SCAN_DEPTH = 4;

    private final SkillProperties properties;
    private final SkillRegistry skillRegistry;

    public SkillInstaller(SkillProperties properties, SkillRegistry skillRegistry) {
        this.properties = properties;
        this.skillRegistry = skillRegistry;
    }

    /**
     * 安装技能。
     *
     * @param repoUrl   Git 地址：{@code owner/repo} 简写、{@code https://...} 或 {@code git@...}
     * @param skillPath 仓库内的技能子目录（如 {@code skills/webapp-testing}）；留空则自动发现：
     *                  仓库根有 SKILL.md 时整仓作为一个技能，否则扫描一级子目录里所有含 SKILL.md 的技能
     * @return 已安装（覆盖安装也算）的技能目录名，已同步刷新注册表
     */
    public List<String> install(String repoUrl, String skillPath) {
        if (!properties.isInstallEnabled()) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN,
                    "技能安装功能已关闭（app.skills.install-enabled=false）");
        }
        String url = normalizeRepoUrl(repoUrl);
        Path root = skillRegistry.externalRoot();
        Path temp = null;
        try {
            log.info("开始安装技能：repo={}, skillPath={}", url, displaySkillPath(skillPath));
            Files.createDirectories(root);
            temp = Files.createTempDirectory("swag-skill-");
            gitClone(url, temp);
            Path source = resolveSource(temp, skillPath);
            List<String> installed = copySkills(source, root);
            if (installed.isEmpty()) {
                String pathHint = skillPath == null || skillPath.isBlank() ? "" : "：" + skillPath;
                List<String> candidates = findSkillCandidates(temp);
                String candidateHint = candidates.isEmpty()
                        ? ""
                        : "；仓库内可选的技能路径（用 skillPath 指定）：" + String.join("、", candidates);
                throw new ResponseStatusException(HttpStatus.BAD_REQUEST,
                        "仓库中没有找到含 SKILL.md 的技能目录" + pathHint + candidateHint);
            }
            skillRegistry.refresh();
            log.info("技能安装完成：{} -> {}", url, installed);
            return installed;
        } catch (ResponseStatusException e) {
            log.warn("技能安装失败：repo={}, skillPath={}, status={}, reason={}",
                    url, displaySkillPath(skillPath), e.getStatusCode().value(), e.getReason());
            throw e;
        } catch (IOException e) {
            log.error("技能安装遇到文件系统错误：repo={}, skillPath={}",
                    url, displaySkillPath(skillPath), e);
            throw new ResponseStatusException(HttpStatus.INTERNAL_SERVER_ERROR,
                    "安装技能失败：" + e.getMessage(), e);
        } finally {
            if (temp != null) {
                try {
                    deleteRecursively(temp);
                } catch (IOException e) {
                    log.warn("清理临时目录失败：{}（{}）", temp, e.toString());
                }
            }
        }
    }

    /** 把用户给的各种写法规范成 git 能识别的地址。 */
    static String normalizeRepoUrl(String repoUrl) {
        if (repoUrl == null || repoUrl.isBlank()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "repoUrl 不能为空");
        }
        String url = repoUrl.strip();
        // 防参数注入：绝不允许以 - 开头
        if (url.startsWith("-")) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "repoUrl 非法：" + repoUrl);
        }
        if (SHORTHAND.matcher(url).matches()) {
            return "https://github.com/" + url + ".git";
        }
        if (url.startsWith("https://") || url.startsWith("http://")
                || url.startsWith("git@") || url.startsWith("ssh://")) {
            return url;
        }
        throw new ResponseStatusException(HttpStatus.BAD_REQUEST,
                "repoUrl 只支持 https://、ssh://、git@ 或 owner/repo 简写：" + repoUrl);
    }

    private void gitClone(String url, Path target) throws IOException {
        Path logFile = Files.createTempFile("swag-skill-git-", ".log");
        try {
            ProcessBuilder builder = new ProcessBuilder("git", "clone", "--depth", "1", url, target.toString());
            // 禁止 Git 等待终端输入用户名、密码或凭据；安装接口必须在有限时间内返回结果。
            configureNonInteractiveGit(builder);
            builder.redirectErrorStream(true);
            builder.redirectOutput(logFile.toFile());
            Process process;
            try {
                process = builder.start();
            } catch (IOException e) {
                log.error("无法启动 git clone：repo={}", url, e);
                throw new ResponseStatusException(HttpStatus.INTERNAL_SERVER_ERROR,
                        "无法执行 git，请确认后端所在机器已安装 git：" + e.getMessage(), e);
            }
            try {
                boolean finished = process.waitFor(Math.max(1, properties.getInstallTimeoutSeconds()), TimeUnit.SECONDS);
                if (!finished) {
                    process.destroyForcibly();
                    throw new ResponseStatusException(HttpStatus.GATEWAY_TIMEOUT,
                            "git clone 超时（" + properties.getInstallTimeoutSeconds() + " 秒）：" + url);
                }
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                throw new ResponseStatusException(HttpStatus.INTERNAL_SERVER_ERROR, "安装被中断");
            } finally {
                if (process.isAlive()) {
                    process.destroyForcibly();
                }
            }
            String output = Files.exists(logFile) ? Files.readString(logFile, StandardCharsets.UTF_8) : "";
            if (process.exitValue() != 0) {
                String detail = tail(output);
                log.warn("git clone 失败：repo={}, exitCode={}, output={}", url, process.exitValue(), detail);
                throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "git clone 失败：" + detail);
            }
        } finally {
            Files.deleteIfExists(logFile);
        }
    }

    /** Package-private for a focused test; keeps non-interactive Git policy inside the installer. */
    static void configureNonInteractiveGit(ProcessBuilder builder) {
        builder.environment().put("GIT_TERMINAL_PROMPT", "0");
    }

    static Path resolveSource(Path cloneDir, String skillPath) {
        if (skillPath == null || skillPath.isBlank()) {
            return cloneDir;
        }
        Path candidate = cloneDir.resolve(skillPath.strip()).normalize();
        if (!candidate.startsWith(cloneDir)) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "skillPath 非法：" + skillPath);
        }
        if (!Files.isDirectory(candidate)) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "仓库中不存在目录：" + skillPath);
        }
        return candidate;
    }

    /** 拷贝技能目录；已存在同名技能时覆盖安装。 */
    List<String> copySkills(Path source, Path root) throws IOException {
        List<Path> skillDirs;
        if (Files.isRegularFile(source.resolve("SKILL.md"))) {
            skillDirs = List.of(source);
        } else {
            try (Stream<Path> children = Files.list(source)) {
                skillDirs = children
                        .filter(Files::isDirectory)
                        .filter(dir -> !dir.getFileName().toString().startsWith("."))
                        .filter(dir -> Files.isRegularFile(dir.resolve("SKILL.md")))
                        .sorted()
                        .toList();
            }
        }
        List<String> installed = new ArrayList<>();
        for (Path dir : skillDirs) {
            String folderName = targetFolderName(dir);
            Path target = root.resolve(folderName).normalize();
            if (!target.startsWith(root)) {
                log.warn("跳过非法技能目录名：{}", folderName);
                continue;
            }
            if (Files.exists(target)) {
                deleteRecursively(target);
            }
            copyRecursively(dir, target);
            installed.add(folderName);
        }
        return installed;
    }

    /** 目录名优先取 frontmatter 的 name（整仓单一技能时临时目录名不可读，必须回退到 name）。 */
    static String targetFolderName(Path skillDir) {
        try {
            String raw = Files.readString(skillDir.resolve("SKILL.md"), StandardCharsets.UTF_8);
            SkillMarkdown.Result result = SkillMarkdown.parse(skillDir.getFileName().toString(), raw);
            if (result.ok()) {
                return result.parsed().name();
            }
        } catch (IOException ignored) {
            // 读不到就退回目录名
        }
        return skillDir.getFileName().toString();
    }

    /**
     * 在仓库里找含 SKILL.md 的目录（有界深度），用于安装失败时提示可选路径。
     * 形如 anthropics/skills 这种 {@code skills/<name>/SKILL.md} 的两级仓库靠它给出可用的 skillPath。
     */
    static List<String> findSkillCandidates(Path root) throws IOException {
        try (Stream<Path> walk = Files.walk(root, CANDIDATE_SCAN_DEPTH)) {
            return walk.filter(Files::isDirectory)
                    .filter(dir -> !dir.equals(root))
                    .filter(dir -> !isInsideGitDir(root, dir))
                    .filter(dir -> Files.isRegularFile(dir.resolve("SKILL.md")))
                    .map(dir -> root.relativize(dir).toString())
                    .sorted()
                    .limit(20)
                    .toList();
        }
    }

    private static boolean isInsideGitDir(Path root, Path dir) {
        for (Path segment : root.relativize(dir)) {
            if (".git".equals(segment.toString())) {
                return true;
            }
        }
        return false;
    }

    private static void copyRecursively(Path source, Path target) throws IOException {
        try (Stream<Path> walk = Files.walk(source)) {
            for (Path path : walk.sorted().toList()) {
                Path relative = source.relativize(path);
                if (relative.getNameCount() > 0 && ".git".equals(relative.getName(0).toString())) {
                    continue;
                }
                Path destination = target.resolve(relative);
                if (Files.isDirectory(path)) {
                    Files.createDirectories(destination);
                } else {
                    Files.createDirectories(destination.getParent());
                    Files.copy(path, destination,
                            StandardCopyOption.REPLACE_EXISTING, StandardCopyOption.COPY_ATTRIBUTES);
                }
            }
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

    /** 错误信息只回传 git 输出的末尾若干字符，避免把整段日志塞进响应。 */
    private static String tail(String output) {
        String flat = output == null ? "" : output.strip();
        if (flat.length() <= 500) {
            return flat;
        }
        return "…" + flat.substring(flat.length() - 500);
    }

    private static String displaySkillPath(String skillPath) {
        return skillPath == null || skillPath.isBlank() ? "<auto>" : skillPath.strip();
    }
}

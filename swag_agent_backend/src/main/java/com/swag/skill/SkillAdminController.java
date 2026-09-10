package com.swag.skill;

import com.swag.auth.AppUserDO;
import com.swag.auth.AuthService;
import com.swag.auth.UserContextHolder;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

import java.util.List;

/**
 * 技能管理端 REST（仅 ADMIN 角色可访问，其余一律 403）。
 * <p>
 * 覆盖：技能列表（内置 + 外部）、启停、重新扫描、从 Git 仓库安装、删除外部技能。
 * 技能只作为提示词注入，因此这里的操作不会影响工具审计与确认流程。
 */
@RestController
@RequestMapping("/auth/admin/skills")
public class SkillAdminController {

    public static final String ROLE_ADMIN = "ADMIN";

    private final AuthService authService;
    private final SkillRegistry skillRegistry;
    private final SkillInstaller skillInstaller;

    public SkillAdminController(AuthService authService,
                                SkillRegistry skillRegistry,
                                SkillInstaller skillInstaller) {
        this.authService = authService;
        this.skillRegistry = skillRegistry;
        this.skillInstaller = skillInstaller;
    }

    /** 技能视图：bodyChars 用于判断注入体积，filePath 便于排查来源。 */
    public record SkillView(String name, String description, boolean enabled,
                            String source, int bodyChars, String filePath) {
    }

    public record ToggleRequest(Boolean enabled) {
    }

    public record InstallRequest(String repoUrl, String skillPath) {
    }

    public record InstallResponse(List<String> installed, List<SkillView> skills) {
    }

    /** 全部技能（含停用的）。 */
    @GetMapping
    public List<SkillView> list() {
        requireAdmin();
        return views();
    }

    /** 启停一个技能；下一条消息即按新状态注入 system prompt。 */
    @PutMapping("/{name}")
    public SkillView toggle(@PathVariable String name, @RequestBody ToggleRequest request) {
        requireAdmin();
        if (request == null || request.enabled() == null) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "缺少 enabled 字段");
        }
        if (!skillRegistry.setEnabled(name, request.enabled())) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "技能不存在：" + name);
        }
        return skillRegistry.find(name)
                .map(this::toView)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "技能不存在：" + name));
    }

    /** 重新扫描内置/外部目录（手工往目录里拷技能后可用）。 */
    @PostMapping("/refresh")
    public List<SkillView> refresh() {
        requireAdmin();
        skillRegistry.refresh();
        return views();
    }

    /** 从 Git 仓库安装技能（如 {"repoUrl": "anthropics/skills", "skillPath": "webapp-testing"}）。 */
    @PostMapping("/install")
    public InstallResponse install(@RequestBody InstallRequest request) {
        requireAdmin();
        if (request == null) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "请求体不能为空");
        }
        List<String> installed = skillInstaller.install(request.repoUrl(), request.skillPath());
        return new InstallResponse(installed, views());
    }

    /** 删除一个外部技能（内置技能不可删）。 */
    @DeleteMapping("/{name}")
    public void delete(@PathVariable String name) {
        requireAdmin();
        if (!skillRegistry.deleteExternal(name)) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST,
                    "技能不存在或为内置技能，无法删除：" + name);
        }
    }

    private List<SkillView> views() {
        return skillRegistry.list().stream().map(this::toView).toList();
    }

    private SkillView toView(SkillManifest manifest) {
        return new SkillView(manifest.name(), manifest.description(),
                skillRegistry.isEnabled(manifest.name()), manifest.source(),
                manifest.body().length(), manifest.filePath());
    }

    private void requireAdmin() {
        Long userId = UserContextHolder.currentUserId();
        AppUserDO user = userId == null ? null : authService.findById(userId).orElse(null);
        if (user == null || !ROLE_ADMIN.equals(user.getRole())) {
            throw new ResponseStatusException(HttpStatus.FORBIDDEN, "仅管理员可执行该操作");
        }
    }
}

package com.swag.notes;

import com.swag.auth.UserContextHolder;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

import java.util.List;

/**
 * Markdown 笔记 REST 接口（供「笔记」页使用）。
 * <p>
 * 路径均为用户笔记目录内的相对路径（/ 分隔，UTF-8），如 {@code 工作/周报.md}；
 * 文件操作仅接受 .md 笔记。删除一律先进回收站（7 天后自动清除），可恢复。
 */
@RestController
@RequestMapping("/notes")
public class NotesController {

    public record DirRequest(String path) {
    }

    public record DeleteDirRequest(String path, String mode) {
    }

    public record RenameRequest(String from, String to) {
    }

    public record SaveRequest(String path, String content) {
    }

    private final NotesService service;

    public NotesController(NotesService service) {
        this.service = service;
    }

    /** 用户笔记目录树。 */
    @GetMapping("/tree")
    public NotesViews.Node tree() {
        return service.tree(currentUser());
    }

    /** 读取一篇笔记源码。 */
    @GetMapping("/file")
    public NotesViews.FileView read(@RequestParam String path) {
        return service.read(currentUser(), path);
    }

    /** 新建 / 覆盖一篇笔记。 */
    @PutMapping("/file")
    public NotesViews.SaveResult save(@RequestBody SaveRequest request) {
        if (request.path() == null || request.path().isBlank()) {
            throw badRequest("笔记路径不能为空");
        }
        return service.save(currentUser(), request.path(), request.content());
    }

    /** 删除一篇笔记 → 移入回收站（可恢复）。 */
    @DeleteMapping("/file")
    public void deleteFile(@RequestParam String path) {
        service.deleteFile(currentUser(), path);
    }

    /** 新建文件夹（可含子路径，自动创建父级）。 */
    @PostMapping("/dir")
    public void createDir(@RequestBody DirRequest request) {
        if (request.path() == null || request.path().isBlank()) {
            throw badRequest("文件夹路径不能为空");
        }
        service.createDir(currentUser(), request.path());
    }

    /**
     * 删除文件夹：
     * mode=trash（默认）整个文件夹（含内容）移入回收站；
     * mode=flatten 删除文件夹但把其中所有笔记平铺移入「未分类」。
     */
    @DeleteMapping("/dir")
    public void deleteDir(@RequestParam String path,
                          @RequestParam(defaultValue = "trash") String mode) {
        Long userId = currentUser();
        if ("flatten".equals(mode)) {
            service.deleteDirFlatten(userId, path);
        }
        else if ("trash".equals(mode)) {
            service.deleteDirToTrash(userId, path);
        }
        else {
            throw badRequest("mode 仅支持 trash / flatten");
        }
    }

    /** 重命名 / 移动文件或文件夹。 */
    @PostMapping("/rename")
    public void rename(@RequestBody RenameRequest request) {
        service.rename(currentUser(), request.from(), request.to());
    }

    // ---------- 回收站 ----------

    /** 回收站条目列表。 */
    @GetMapping("/trash")
    public List<NotesViews.TrashView> trash() {
        return service.listTrash(currentUser());
    }

    /** 恢复回收站条目（原目录仍在 → 放回原处，否则进「未分类」）。 */
    @PostMapping("/trash/{id}/restore")
    public void restore(@PathVariable String id) {
        service.restore(currentUser(), id);
    }

    /** 永久删除某条回收站记录。 */
    @DeleteMapping("/trash/{id}")
    public void deleteTrashEntry(@PathVariable String id) {
        service.deleteTrashEntry(currentUser(), id);
    }

    /** 清空回收站。 */
    @DeleteMapping("/trash")
    public void clearTrash() {
        service.clearTrash(currentUser());
    }

    private Long currentUser() {
        Long userId = UserContextHolder.currentUserId();
        if (userId == null) {
            throw new ResponseStatusException(HttpStatus.UNAUTHORIZED, "未登录");
        }
        return userId;
    }

    private ResponseStatusException badRequest(String message) {
        return new ResponseStatusException(HttpStatus.BAD_REQUEST, message);
    }
}

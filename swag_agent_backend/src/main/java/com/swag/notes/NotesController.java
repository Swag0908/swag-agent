package com.swag.notes;

import com.swag.auth.UserContextHolder;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.server.ResponseStatusException;

/**
 * Markdown 笔记 REST 接口（供「笔记」页使用）。
 * <p>
 * 路径均为用户笔记目录内的相对路径（/ 分隔，UTF-8），如 {@code 工作/周报.md}；
 * 文件操作仅接受 .md 笔记。
 */
@RestController
@RequestMapping("/notes")
public class NotesController {

    public record DirRequest(String path) {
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

    /** 删除一篇笔记。 */
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

    /** 递归删除文件夹。 */
    @DeleteMapping("/dir")
    public void deleteDir(@RequestParam String path) {
        service.deleteDir(currentUser(), path);
    }

    /** 重命名 / 移动文件或文件夹。 */
    @PostMapping("/rename")
    public void rename(@RequestBody RenameRequest request) {
        service.rename(currentUser(), request.from(), request.to());
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

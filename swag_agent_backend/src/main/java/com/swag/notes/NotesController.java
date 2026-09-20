package com.swag.notes;

import com.swag.auth.UserContextHolder;
import org.springframework.core.io.Resource;
import org.springframework.http.ContentDisposition;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.DeleteMapping;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.PutMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.multipart.MultipartFile;
import org.springframework.web.server.ResponseStatusException;

import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
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

    public record LocalImportRequest(List<String> sourcePaths, String targetDir) {
    }

    private final NotesService service;
    private final NotesImportService importService;

    public NotesController(NotesService service, NotesImportService importService) {
        this.service = service;
        this.importService = importService;
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

    /**
     * 新建一篇笔记：同名笔记已存在时返回 409（不覆盖已有笔记）。
     */
    @PostMapping("/file")
    public NotesViews.SaveResult create(@RequestBody SaveRequest request) {
        if (request.path() == null || request.path().isBlank()) {
            throw badRequest("笔记路径不能为空");
        }
        return service.create(currentUser(), request.path(), request.content());
    }

    /** 保存（新建或覆盖）一篇笔记。 */
    @PutMapping("/file")
    public NotesViews.SaveResult save(@RequestBody SaveRequest request) {
        if (request.path() == null || request.path().isBlank()) {
            throw badRequest("笔记路径不能为空");
        }
        return service.save(currentUser(), request.path(), request.content());
    }

    /** 返回当前实例允许本地导入的根目录，供笔记页向用户解释路径边界。 */
    @GetMapping("/import/config")
    public NotesViews.ImportConfig importConfig() {
        currentUser();
        return importService.config();
    }

    /** 从运行后端的机器上、配置允许的目录内批量导入 Markdown。 */
    @PostMapping("/import/local")
    public NotesViews.ImportResult importLocal(@RequestBody LocalImportRequest request) {
        if (request == null) {
            throw badRequest("请求体不能为空");
        }
        return importService.importLocal(currentUser(), request.sourcePaths(), request.targetDir());
    }

    /** 浏览器批量上传；选择目录时 relativePaths 保留层级，以便解析并复制引用附件。 */
    @PostMapping(value = "/import/upload", consumes = MediaType.MULTIPART_FORM_DATA_VALUE)
    public NotesViews.ImportResult importUpload(
            @RequestParam("files") List<MultipartFile> files,
            @RequestParam(value = "relativePaths", required = false) List<String> relativePaths,
            @RequestParam(value = "targetDir", required = false) String targetDir) {
        List<NotesImportService.UploadPart> parts = new ArrayList<>();
        for (int i = 0; i < files.size(); i++) {
            String relative = relativePaths != null && i < relativePaths.size()
                    ? relativePaths.get(i)
                    : files.get(i).getOriginalFilename();
            parts.add(new NotesImportService.UploadPart(relative, files.get(i)));
        }
        return importService.importUploads(currentUser(), parts, targetDir);
    }

    /** 仅向当前用户返回其导入时复制的资源；危险类型强制下载，不在同源页面内执行。 */
    @GetMapping("/resource")
    public ResponseEntity<Resource> resource(@RequestParam String bundle, @RequestParam String name) {
        NotesViews.ResourceView view = importService.resource(currentUser(), bundle, name);
        ContentDisposition disposition = (view.inline()
                ? ContentDisposition.inline()
                : ContentDisposition.attachment())
                .filename(view.fileName(), StandardCharsets.UTF_8)
                .build();
        return ResponseEntity.ok()
                .header(HttpHeaders.CONTENT_DISPOSITION, disposition.toString())
                .header("X-Content-Type-Options", "nosniff")
                .contentType(MediaType.parseMediaType(view.contentType()))
                .body(view.resource());
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

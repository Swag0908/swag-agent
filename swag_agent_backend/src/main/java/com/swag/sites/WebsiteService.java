package com.swag.sites;

import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;

import java.net.URI;
import java.net.URISyntaxException;
import java.time.LocalDateTime;
import java.time.ZoneId;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * 常用网站业务逻辑：文件夹树维护与书签 CRUD。
 */
@Service
public class WebsiteService {

    public static final ZoneId ZONE = ZoneId.of("Asia/Shanghai");

    private final WebsiteRepository repository;

    public WebsiteService(WebsiteRepository repository) {
        this.repository = repository;
    }

    public WebsiteViews.Library library(Long userId, Long folderId, String query,
                                        boolean unclassifiedOnly) {
        List<WebsiteFolderDO> folders = repository.listFolders(userId);
        List<WebsiteBookmarkDO> allBookmarks = repository.listBookmarks(userId, null, null, false);
        Map<Long, List<Long>> descendants = buildDescendants(folders);

        Map<Long, Integer> subtreeCounts = new HashMap<>();
        for (WebsiteFolderDO folder : folders) {
            Set<Long> ids = new HashSet<>();
            collectFolderIds(folder.getId(), descendants, ids);
            int count = 0;
            for (WebsiteBookmarkDO bookmark : allBookmarks) {
                if (bookmark.getFolderId() != null && ids.contains(bookmark.getFolderId())) {
                    count++;
                }
            }
            subtreeCounts.put(folder.getId(), count);
        }

        List<WebsiteViews.FolderNode> tree = buildTree(folders, subtreeCounts, null);
        List<WebsiteBookmarkDO> filtered = repository.listBookmarks(
                userId, folderId, query, unclassifiedOnly);
        List<WebsiteViews.BookmarkView> views = filtered.stream()
                .map(WebsiteViews.BookmarkView::from)
                .toList();
        return new WebsiteViews.Library(tree, views, views.size());
    }

    @Transactional
    public WebsiteViews.FolderNode createFolder(Long userId, String name, Long parentId) {
        String cleanName = requireName(name, "文件夹名称不能为空");
        ensureParent(userId, parentId);
        WebsiteFolderDO folder = new WebsiteFolderDO();
        folder.setUserId(userId);
        folder.setName(cleanName);
        folder.setParentId(parentId);
        folder.setSortOrder(nextFolderOrder(userId, parentId));
        LocalDateTime now = LocalDateTime.now(ZONE);
        folder.setCreatedAt(now);
        folder.setUpdatedAt(now);
        WebsiteFolderDO created = repository.insertFolder(folder);
        return new WebsiteViews.FolderNode(created.getId(), created.getName(), created.getParentId(),
                created.getSortOrder(), 0, List.of());
    }

    @Transactional
    public WebsiteViews.FolderNode updateFolder(Long userId, Long id, String name, Long parentId) {
        WebsiteFolderDO folder = resolveFolder(userId, id);
        String cleanName = requireName(name, "文件夹名称不能为空");
        ensureParent(userId, parentId);
        if (parentId != null) {
            ensureNotDescendant(userId, id, parentId);
        }
        LocalDateTime now = LocalDateTime.now(ZONE);
        repository.updateFolder(id, userId, cleanName, parentId, now);
        folder.setName(cleanName);
        folder.setParentId(parentId);
        folder.setUpdatedAt(now);
        return new WebsiteViews.FolderNode(folder.getId(), folder.getName(), folder.getParentId(),
                folder.getSortOrder(), 0, List.of());
    }

    @Transactional
    public void deleteFolder(Long userId, Long id, boolean cascade) {
        WebsiteFolderDO folder = resolveFolder(userId, id);
        List<WebsiteFolderDO> folders = repository.listFolders(userId);
        Map<Long, List<Long>> descendants = buildDescendants(folders);
        Set<Long> ids = new HashSet<>();
        collectFolderIds(id, descendants, ids);

        List<WebsiteBookmarkDO> bookmarks = repository.listBookmarks(userId, null, null, false);
        long bookmarkCount = bookmarks.stream()
                .filter(b -> b.getFolderId() != null && ids.contains(b.getFolderId()))
                .count();
        long childFolderCount = ids.size() - 1;

        if (!cascade && (bookmarkCount > 0 || childFolderCount > 0)) {
            throw new ResponseStatusException(HttpStatus.CONFLICT,
                    "该文件夹不为空，确认删除其中的 " + bookmarkCount + " 个网站"
                            + (childFolderCount > 0 ? "和 " + childFolderCount + " 个子文件夹" : "")
                            + "？");
        }

        repository.deleteBookmarksByFolders(new ArrayList<>(ids), userId);
        repository.deleteFolders(new ArrayList<>(ids), userId);
    }

    @Transactional
    public WebsiteViews.BookmarkView createBookmark(
            Long userId, String name, String url, String description,
            String iconUrl, Long folderId) {
        String cleanName = requireName(name, "网站名称不能为空");
        String cleanUrl = normalizeUrl(url);
        ensureFolder(userId, folderId);
        WebsiteBookmarkDO bookmark = new WebsiteBookmarkDO();
        bookmark.setUserId(userId);
        bookmark.setName(cleanName);
        bookmark.setUrl(cleanUrl);
        bookmark.setDescription(cleanNullable(description));
        bookmark.setIconUrl(cleanNullable(iconUrl));
        bookmark.setFolderId(folderId);
        bookmark.setSortOrder(nextBookmarkOrder(userId, folderId));
        LocalDateTime now = LocalDateTime.now(ZONE);
        bookmark.setCreatedAt(now);
        bookmark.setUpdatedAt(now);
        return WebsiteViews.BookmarkView.from(repository.insertBookmark(bookmark));
    }

    @Transactional
    public WebsiteViews.BookmarkView updateBookmark(
            Long userId, Long id, String name, String url, String description,
            String iconUrl, Long folderId) {
        WebsiteBookmarkDO bookmark = resolveBookmark(userId, id);
        String cleanName = requireName(name, "网站名称不能为空");
        String cleanUrl = normalizeUrl(url);
        ensureFolder(userId, folderId);
        LocalDateTime now = LocalDateTime.now(ZONE);
        repository.updateBookmark(id, userId, cleanName, cleanUrl,
                cleanNullable(description), cleanNullable(iconUrl), folderId, now);
        bookmark.setName(cleanName);
        bookmark.setUrl(cleanUrl);
        bookmark.setDescription(cleanNullable(description));
        bookmark.setIconUrl(cleanNullable(iconUrl));
        bookmark.setFolderId(folderId);
        bookmark.setUpdatedAt(now);
        return WebsiteViews.BookmarkView.from(bookmark);
    }

    @Transactional
    public void deleteBookmark(Long userId, Long id) {
        resolveBookmark(userId, id);
        repository.deleteBookmark(id, userId);
    }

    private List<WebsiteViews.FolderNode> buildTree(
            List<WebsiteFolderDO> folders,
            Map<Long, Integer> counts,
            Long parentId) {
        List<WebsiteViews.FolderNode> result = new ArrayList<>();
        for (WebsiteFolderDO folder : folders) {
            if (sameId(folder.getParentId(), parentId)) {
                result.add(new WebsiteViews.FolderNode(
                        folder.getId(),
                        folder.getName(),
                        folder.getParentId(),
                        folder.getSortOrder(),
                        counts.getOrDefault(folder.getId(), 0),
                        buildTree(folders, counts, folder.getId())));
            }
        }
        return result;
    }

    private Map<Long, List<Long>> buildDescendants(List<WebsiteFolderDO> folders) {
        Map<Long, List<Long>> result = new HashMap<>();
        for (WebsiteFolderDO folder : folders) {
            result.computeIfAbsent(folder.getId(), ignored -> new ArrayList<>());
            if (folder.getParentId() != null) {
                result.computeIfAbsent(folder.getParentId(), ignored -> new ArrayList<>())
                        .add(folder.getId());
            }
        }
        return result;
    }

    private void collectFolderIds(Long id, Map<Long, List<Long>> descendants, Set<Long> result) {
        result.add(id);
        for (Long child : descendants.getOrDefault(id, List.of())) {
            if (!result.contains(child)) {
                collectFolderIds(child, descendants, result);
            }
        }
    }

    private void ensureNotDescendant(Long userId, Long id, Long parentId) {
        List<WebsiteFolderDO> folders = repository.listFolders(userId);
        Map<Long, List<Long>> descendants = buildDescendants(folders);
        Set<Long> ids = new HashSet<>();
        collectFolderIds(id, descendants, ids);
        if (ids.contains(parentId)) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST,
                    "不能把文件夹移动到它自己的子文件夹下");
        }
    }

    private void ensureParent(Long userId, Long parentId) {
        if (parentId == null) {
            return;
        }
        resolveFolder(userId, parentId);
    }

    private void ensureFolder(Long userId, Long folderId) {
        if (folderId == null) {
            return;
        }
        resolveFolder(userId, folderId);
    }

    private WebsiteFolderDO resolveFolder(Long userId, Long id) {
        WebsiteFolderDO folder = repository.findFolderById(id)
                .orElseThrow(() -> new ResponseStatusException(
                        HttpStatus.NOT_FOUND, "文件夹不存在：#" + id));
        if (!folder.getUserId().equals(userId)) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "文件夹不存在：#" + id);
        }
        return folder;
    }

    private WebsiteBookmarkDO resolveBookmark(Long userId, Long id) {
        WebsiteBookmarkDO bookmark = repository.findBookmarkById(id)
                .orElseThrow(() -> new ResponseStatusException(
                        HttpStatus.NOT_FOUND, "网站不存在：#" + id));
        if (!bookmark.getUserId().equals(userId)) {
            throw new ResponseStatusException(HttpStatus.NOT_FOUND, "网站不存在：#" + id);
        }
        return bookmark;
    }

    private int nextFolderOrder(Long userId, Long parentId) {
        return (int) repository.listFolders(userId).stream()
                .filter(f -> sameId(f.getParentId(), parentId))
                .count();
    }

    private int nextBookmarkOrder(Long userId, Long folderId) {
        return repository.listBookmarks(userId, folderId, null, folderId == null).size();
    }

    private String requireName(String name, String message) {
        if (name == null || name.isBlank()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, message);
        }
        String value = name.trim();
        if (value.length() > 64) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "名称不能超过 64 个字符");
        }
        return value;
    }

    private String cleanNullable(String value) {
        if (value == null || value.isBlank()) {
            return null;
        }
        return value.trim();
    }

    /**
     * 规范化网址：缺协议补 https://，仅允许 http/https，返回可入库的标准串。
     * 公开供对话工具在写库前做去重比对。
     */
    public String normalizeUrl(String raw) {
        if (raw == null || raw.isBlank()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "网址不能为空");
        }
        String value = raw.trim();
        if (!value.contains("://")) {
            value = "https://" + value;
        }
        try {
            URI uri = new URI(value);
            String scheme = uri.getScheme();
            String host = uri.getHost();
            if (scheme == null || host == null
                    || !(scheme.equalsIgnoreCase("http") || scheme.equalsIgnoreCase("https"))) {
                throw new ResponseStatusException(HttpStatus.BAD_REQUEST,
                        "请输入合法的 http/https 网址");
            }
            return uri.toString();
        }
        catch (URISyntaxException exception) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "请输入合法的网址");
        }
    }

    private boolean sameId(Long left, Long right) {
        if (left == null || right == null) {
            return left == right;
        }
        return left.equals(right);
    }
}

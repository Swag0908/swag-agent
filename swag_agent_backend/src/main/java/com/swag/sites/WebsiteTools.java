package com.swag.sites;

import org.springframework.ai.chat.model.ToolContext;
import org.springframework.ai.tool.annotation.Tool;
import org.springframework.ai.tool.annotation.ToolParam;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Component;
import org.springframework.web.server.ResponseStatusException;

import java.net.URI;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;

/**
 * 供大模型调用的「常用网站菜单」工具：支持用对话维护当前用户自己的常用网站。
 * <p>
 * 与 {@link com.swag.todo.TodoTools} 一致，用户身份通过 ToolContext 注入（而非 ThreadLocal），
 * 所有读写都限制在当前登录用户自己的数据上（用户维度）。分类以「#id」或「分类名」引用，
 * 其余工具返回的列表里带 #id，模型应优先用 #id 精确定位。
 * <p>
 * 交互约定（供模型遵循）：
 * <ul>
 *   <li>添加网站时若用户给了一个不存在的分类名，不要擅自新建或猜测相近分类，先向用户确认：
 *       新建同名分类，还是放入含义相近的现有分类；得到明确同意后再操作。</li>
 *   <li>删除网站/分类是破坏性操作，先向用户确认再执行。</li>
 * </ul>
 */
@Component
public class WebsiteTools {

    private final WebsiteService service;

    public WebsiteTools(WebsiteService service) {
        this.service = service;
    }

    private Long userId(ToolContext context) {
        Object value = context.getContext().get("userId");
        if (value instanceof Number number) {
            return number.longValue();
        }
        if (value instanceof String text && !text.isBlank()) {
            return Long.parseLong(text);
        }
        throw new IllegalStateException("未登录，无法操作常用网站");
    }

    // ------------------------------------------------------------------
    // 查询
    // ------------------------------------------------------------------

    @Tool(description = "列出当前用户（我）常用网站菜单里的「分类树」：每个分类的 #id、名称、"
            + "层级路径、内含网站数。其它网站工具请优先按这里的 #id 引用分类")
    public String listSiteFolders(ToolContext toolContext) {
        Long uid = userId(toolContext);
        WebsiteViews.Library lib = library(uid);
        FolderIndex index = indexOf(lib);
        if (lib.folders().isEmpty()) {
            return "常用网站菜单里还没有分类。可对未分类的网站直接使用 addSiteBookmark，"
                    + "或用 createSiteFolder 先建分类。";
        }
        StringBuilder sb = new StringBuilder("我的常用网站分类（共 ")
                .append(index.byId.size()).append(" 个）：\n");
        appendFolderTree(sb, lib.folders(), index, 0);
        long unclassified = lib.bookmarks().stream()
                .filter(b -> b.folderId() == null)
                .count();
        if (unclassified > 0) {
            sb.append("未分类网站：").append(unclassified).append(" 个（未归入任何分类）\n");
        }
        return sb.toString().trim();
    }

    @Tool(description = "查询当前用户（我）常用网站菜单里的网站列表：每条含 #id、名称、网址、"
            + "所属分类、备注。keyword 可空（空=全部），按名称/网址/备注模糊匹配；"
            + "categoryId 传分类 #id 只查该分类直属的网站。"
            + "可用于查找网站 #id 以便修改/删除，或添加前查重")
    public String listSiteBookmarks(
            @ToolParam(description = "搜索关键词，匹配名称/网址/备注，可为空") String keyword,
            @ToolParam(description = "分类 #id，只列出该分类下的网站，可为空") String categoryId,
            ToolContext toolContext) {
        Long uid = userId(toolContext);
        WebsiteViews.Library lib = library(uid);
        FolderIndex index = indexOf(lib);

        Long folderId = null;
        boolean unclassified = false;
        if (categoryId != null && !categoryId.isBlank()) {
            Long parsed = parseId(categoryId);
            if (parsed != null) {
                if (index.byId.containsKey(parsed)) {
                    folderId = parsed;
                }
                else {
                    return "分类不存在：#" + parsed + "，请先用 listSiteFolders 查看现有分类。";
                }
            }
            else if (isRootToken(categoryId)) {
                unclassified = true;
            }
            else {
                List<Long> ids = idsByFolderName(index, categoryId.trim());
                if (ids.isEmpty()) {
                    return "未找到名为「" + categoryId.trim() + "」的分类，"
                            + "请先用 listSiteFolders 查看现有分类。";
                }
                if (ids.size() > 1) {
                    return ambiguousFoldersMessage(index, ids);
                }
                folderId = ids.get(0);
            }
        }
        if (keyword == null || keyword.isBlank()) {
            keyword = null;
        }
        List<WebsiteViews.BookmarkView> views = keyword == null && folderId == null && !unclassified
                ? lib.bookmarks()
                : service.library(uid, folderId, keyword, unclassified).bookmarks();
        if (views.isEmpty()) {
            if (keyword != null) {
                return "没有找到匹配「" + keyword + "」的网站。";
            }
            return folderId != null
                    ? "分类「" + folderName(index, folderId) + "」下还没有网站。"
                    : unclassified ? "未分类下还没有网站。"
                    : "常用网站菜单还是空的，可以直接用 addSiteBookmark 添加。";
        }
        StringBuilder sb = new StringBuilder("我的常用网站（共 ").append(views.size()).append(" 个）：\n");
        for (WebsiteViews.BookmarkView b : views) {
            sb.append("#").append(b.id())
                    .append(" ").append(b.name());
            if (b.folderId() != null) {
                sb.append("（分类：").append(pathOf(index, b.folderId())).append("）");
            }
            else {
                sb.append("（未分类）");
            }
            sb.append("\n  网址：").append(b.url());
            if (b.description() != null && !b.description().isBlank()) {
                sb.append("\n  备注：").append(b.description());
            }
            sb.append("\n");
        }
        return sb.toString().trim();
    }

    // ------------------------------------------------------------------
    // 网站增删改
    // ------------------------------------------------------------------

    @Tool(description = "把网站添加到当前用户（我）的常用网站菜单（用户维度，只会加到我的菜单）。"
            + "url 必填。category 可空（空=未分类），支持分类 #id 或分类名；"
            + "分类名必须与现有分类完全一致：若不存在，除非用户已明确同意新建，否则先向用户确认是"
            + "「新建同名分类」还是「放入含义相近的现有分类」（可先用 listSiteFolders 查看），"
            + "用户同意新建后再调用并把 createCategoryIfMissing 设为 true。"
            + "若该网址已存在会直接返回已有记录，不会重复添加。"
            + "name 不填默认取网址域名作为名称，icon 留空前端会自动取图标")
    public String addSiteBookmark(
            @ToolParam(description = "网站链接，必填，如 https://github.com") String url,
            @ToolParam(description = "网站名称，可为空，留空默认取网址域名") String name,
            @ToolParam(description = "备注/用途，可为空") String description,
            @ToolParam(description = "分类 #id 或分类名，可为空（空=未分类），如「#12」或「开发工具」") String category,
            @ToolParam(description = "分类不存在时是否自动新建同名分类；仅当用户明确同意新建时才传 true") Boolean createCategoryIfMissing,
            ToolContext toolContext) {
        Long uid = userId(toolContext);
        try {
            if (url == null || url.isBlank()) {
                return "网址不能为空，请让用户补充网站链接。";
            }
            String normalized = service.normalizeUrl(url);

            WebsiteViews.Library lib = library(uid);
            FolderIndex index = indexOf(lib);
            for (WebsiteViews.BookmarkView b : lib.bookmarks()) {
                if (b.url().equalsIgnoreCase(normalized)) {
                    return "该网址已在我的常用网站里：#" + b.id() + " " + b.name()
                            + (b.folderId() != null
                            ? "（分类：" + pathOf(index, b.folderId()) + "）"
                            : "（未分类）")
                            + "，无需重复添加。如需移动分类或改名可用 updateSiteBookmark。";
                }
            }

            Long folderId = null;
            if (category != null && !category.isBlank()) {
                Long parsed = parseId(category);
                if (parsed != null) {
                    if (!index.byId.containsKey(parsed)) {
                        return "分类不存在：#" + parsed + "，请先用 listSiteFolders 查看现有分类。";
                    }
                    folderId = parsed;
                }
                else if (isRootToken(category)) {
                    folderId = null;
                }
                else {
                    List<Long> ids = idsByFolderName(index, category.trim());
                    if (ids.size() == 1) {
                        folderId = ids.get(0);
                    }
                    else if (ids.size() > 1) {
                        return ambiguousFoldersMessage(index, ids);
                    }
                    else {
                        if (!Boolean.TRUE.equals(createCategoryIfMissing)) {
                            return "我的分类里没有「" + category.trim() + "」。现有分类："
                                    + existingFoldersLine(index)
                                    + "。请先询问用户：新建该分类，还是放入含义相近的现有分类？"
                                    + "用户同意新建后再调用本工具并传 createCategoryIfMissing=true。";
                        }
                        WebsiteViews.FolderNode created =
                                service.createFolder(uid, category.trim(), null);
                        folderId = created.id();
                    }
                }
            }

            String finalName = clean(name);
            if (finalName == null) {
                finalName = defaultName(normalized);
            }
            WebsiteViews.BookmarkView view = service.createBookmark(
                    uid, finalName, normalized, clean(description), null, folderId);
            return "已添加到常用网站：#" + view.id() + " " + view.name()
                    + (folderId != null ? "（分类：" + folderName(index, folderId) + "）" : "（未分类）")
                    + "。网址：" + view.url();
        }
        catch (ResponseStatusException e) {
            return "添加失败：" + reason(e);
        }
    }

    @Tool(description = "修改已添加的网站。ref 为网站 #id 或完整网址或名称；"
            + "只传需要改的字段，未传的字段保留原值；category 传「未分类」可把网站移出分类；"
            + "传新分类 #id/分类名可移动；改网址时会检查是否与其它网站重复")
    public String updateSiteBookmark(
            @ToolParam(description = "要修改的网站：#id、完整网址或名称") String ref,
            @ToolParam(description = "新的网站名称，可空=不改") String name,
            @ToolParam(description = "新的网址，可空=不改") String url,
            @ToolParam(description = "新的备注，可空=不改；传空字符串可清空备注") String description,
            @ToolParam(description = "目标分类 #id 或分类名；传「未分类」=移出分类；可空=分类不变") String category,
            ToolContext toolContext) {
        Long uid = userId(toolContext);
        try {
            if (ref == null || ref.isBlank()) {
                return "请提供要修改的网站（#id、网址或名称）。";
            }
            WebsiteViews.Library lib = library(uid);
            FolderIndex index = indexOf(lib);
            WebsiteViews.BookmarkView current = resolveBookmark(index, lib, ref);

            String finalName = name != null && !name.isBlank() ? name.trim() : current.name();
            String finalUrl = current.url();
            if (url != null && !url.isBlank()) {
                finalUrl = service.normalizeUrl(url);
                for (WebsiteViews.BookmarkView b : lib.bookmarks()) {
                    if (!b.id().equals(current.id()) && b.url().equalsIgnoreCase(finalUrl)) {
                        return "已有其它网站使用该网址：#" + b.id() + " " + b.name()
                                + "，为避免重复请先与用户确认是否仍要修改。";
                    }
                }
            }
            String finalDescription = description == null
                    ? current.description()
                    : description.isBlank() ? null : description.trim();
            String finalIcon = current.iconUrl();
            Long folderId = current.folderId();
            if (category != null && !category.isBlank()) {
                folderId = resolveFolderId(index, category);
            }
            WebsiteViews.BookmarkView view = service.updateBookmark(
                    uid, current.id(), finalName, finalUrl,
                    finalDescription, finalIcon, folderId);
            return "已更新网站 #" + view.id() + " " + view.name()
                    + (view.folderId() != null
                    ? "（分类：" + folderName(index, view.folderId()) + "）"
                    : "（未分类）");
        }
        catch (ResponseStatusException e) {
            return "修改失败：" + reason(e);
        }
    }

    @Tool(description = "从当前用户（我）的常用网站菜单里删除一个网站。"
            + "ref 为网站 #id 或完整网址或名称；删除是不可恢复操作，请先向用户确认再调用")
    public String deleteSiteBookmark(
            @ToolParam(description = "要删除的网站：#id、完整网址或名称") String ref,
            ToolContext toolContext) {
        Long uid = userId(toolContext);
        try {
            WebsiteViews.Library lib = library(uid);
            FolderIndex index = indexOf(lib);
            WebsiteViews.BookmarkView target = resolveBookmark(index, lib, ref);
            service.deleteBookmark(uid, target.id());
            return "已从常用网站删除：#" + target.id() + " " + target.name()
                    + "（" + target.url() + "）。";
        }
        catch (ResponseStatusException e) {
            return "删除失败：" + reason(e);
        }
    }

    // ------------------------------------------------------------------
    // 分类增删改
    // ------------------------------------------------------------------

    @Tool(description = "在当前用户（我）的常用网站菜单里新建一个分类文件夹。"
            + "name 必填；parentCategory 可空=顶层分类，支持父分类 #id 或父分类名。"
            + "若已存在同名分类会提示，请先向用户确认是直接使用还是仍要新建")
    public String createSiteFolder(
            @ToolParam(description = "新分类名称，必填，如「开发工具」") String name,
            @ToolParam(description = "上级分类 #id 或分类名，可空=建为顶层分类") String parentCategory,
            ToolContext toolContext) {
        Long uid = userId(toolContext);
        try {
            if (name == null || name.isBlank()) {
                return "分类名称不能为空，请让用户补充。";
            }
            String cleanName = name.trim();
            WebsiteViews.Library lib = library(uid);
            FolderIndex index = indexOf(lib);
            List<Long> same = idsByFolderName(index, cleanName);
            if (!same.isEmpty()) {
                return "已存在同名分类：" + listFolderIds(index, same)
                        + "。请先询问用户是直接使用现有分类，还是仍要新建一个。";
            }
            Long parentId = null;
            if (parentCategory != null && !parentCategory.isBlank()) {
                parentId = resolveFolderId(index, parentCategory);
            }
            WebsiteViews.FolderNode created = service.createFolder(uid, cleanName, parentId);
            return "已新建分类 #" + created.id() + " " + created.name()
                    + (parentId != null
                    ? "（上级：" + folderName(index, parentId) + "）"
                    : "（顶层分类）");
        }
        catch (ResponseStatusException e) {
            return "创建失败：" + reason(e);
        }
    }

    @Tool(description = "重命名或移动当前用户（我）的分类文件夹。"
            + "folderRef 为分类 #id 或分类名；newName 可空=不改名；"
            + "parentCategory 可空=保持当前位置，传「根目录」可移到顶层")
    public String updateSiteFolder(
            @ToolParam(description = "要修改的分类：#id 或分类名") String folderRef,
            @ToolParam(description = "新的分类名称，可空=不改名") String newName,
            @ToolParam(description = "新的上级分类 #id 或分类名；传「根目录」=移到顶层；可空=不动") String parentCategory,
            ToolContext toolContext) {
        Long uid = userId(toolContext);
        try {
            WebsiteViews.Library lib = library(uid);
            FolderIndex index = indexOf(lib);
            Long folderId = resolveFolderId(index, folderRef);

            WebsiteViews.FolderNode folder = index.byId.get(folderId);
            String finalName = folder.name();
            if (newName != null && !newName.isBlank()) {
                String cleanName = newName.trim();
                if (!cleanName.equals(folder.name())) {
                    List<Long> same = idsByFolderName(index, cleanName);
                    if (!same.isEmpty()) {
                        return "已存在同名分类：" + listFolderIds(index, same)
                                + "，为避免混乱请先与用户确认。";
                    }
                }
                finalName = cleanName;
            }
            Long parentId = folder.parentId();
            if (parentCategory != null && !parentCategory.isBlank()) {
                parentId = resolveFolderId(index, parentCategory);
            }
            service.updateFolder(uid, folderId, finalName, parentId);
            return "已更新分类 #" + folderId + " " + finalName
                    + (parentId != null
                    ? "（上级：" + folderName(index, parentId) + "）"
                    : "（顶层分类）");
        }
        catch (ResponseStatusException e) {
            return "更新失败：" + reason(e);
        }
    }

    @Tool(description = "删除当前用户（我）的一个分类文件夹。cascade=false（默认）时，"
            + "若分类下还有网站或子分类会返回提示而不删除，需先向用户确认后"
            + "再以 cascade=true 级联删除其中的网站和子分类；删除不可恢复，请先确认")
    public String deleteSiteFolder(
            @ToolParam(description = "要删除的分类：#id 或分类名") String folderRef,
            @ToolParam(description = "是否连同其中网站/子分类一并删除，默认 false；需用户明确同意级联删除才传 true") Boolean cascade,
            ToolContext toolContext) {
        Long uid = userId(toolContext);
        try {
            WebsiteViews.Library lib = library(uid);
            FolderIndex index = indexOf(lib);
            Long folderId = resolveFolderId(index, folderRef);
            String label = folderName(index, folderId);
            service.deleteFolder(uid, folderId, Boolean.TRUE.equals(cascade));
            return "已删除分类 " + label
                    + (Boolean.TRUE.equals(cascade) ? "（含其中网站与子分类）" : "") + "。";
        }
        catch (ResponseStatusException e) {
            // 非空分类且未级联时返回提示文案，供模型转述给用户并征得同意。
            return reason(e);
        }
    }

    // ------------------------------------------------------------------
    // 内部：索引与引用解析
    // ------------------------------------------------------------------

    private WebsiteViews.Library library(Long uid) {
        return service.library(uid, null, null, false);
    }

    /** 分类节点索引：id -> 节点；同一用户库内必然属于该用户。 */
    private FolderIndex indexOf(WebsiteViews.Library lib) {
        FolderIndex index = new FolderIndex();
        flatten(lib.folders(), index.byId);
        return index;
    }

    private void flatten(List<WebsiteViews.FolderNode> nodes, Map<Long, WebsiteViews.FolderNode> out) {
        for (WebsiteViews.FolderNode node : nodes) {
            out.put(node.id(), node);
            if (node.children() != null && !node.children().isEmpty()) {
                flatten(node.children(), out);
            }
        }
    }

    private void appendFolderTree(StringBuilder sb, List<WebsiteViews.FolderNode> nodes,
                                  FolderIndex index, int depth) {
        for (WebsiteViews.FolderNode node : nodes) {
            sb.append("  ".repeat(depth))
                    .append("#").append(node.id()).append(" ").append(node.name())
                    .append("（").append(node.bookmarkCount()).append(" 个网站）\n");
            if (node.children() != null && !node.children().isEmpty()) {
                appendFolderTree(sb, node.children(), index, depth + 1);
            }
        }
    }

    /** 按名字（忽略大小写、去掉首尾空格）找分类 id 列表。 */
    private List<Long> idsByFolderName(FolderIndex index, String name) {
        List<Long> ids = new ArrayList<>();
        for (WebsiteViews.FolderNode node : index.byId.values()) {
            if (node.name().trim().equalsIgnoreCase(name)) {
                ids.add(node.id());
            }
        }
        return ids;
    }

    private String ambiguousFoldersMessage(FolderIndex index, List<Long> ids) {
        return "同名分类有多个：" + listFolderIds(index, ids)
                + "。请让用户确认用哪一个（可按 #id 指定）。";
    }

    private String listFolderIds(FolderIndex index, List<Long> ids) {
        List<String> parts = new ArrayList<>();
        for (Long id : ids) {
            parts.add("#" + id + " " + folderName(index, id));
        }
        return String.join("、", parts);
    }

    private String existingFoldersLine(FolderIndex index) {
        List<String> parts = new ArrayList<>();
        for (WebsiteViews.FolderNode node : flattenNodesOf(index)) {
            parts.add("#" + node.id() + " " + node.name());
        }
        return parts.isEmpty() ? "暂无分类" : String.join("、", parts);
    }

    private List<WebsiteViews.FolderNode> flattenNodesOf(FolderIndex index) {
        // FolderIndex 不保存树根顺序，这里用 byId 排序不保证原始树顺序；
        // 列表仅为给模型的候选提示，顺序不影响正确性。
        return new ArrayList<>(index.byId.values());
    }

    private String folderName(FolderIndex index, Long id) {
        WebsiteViews.FolderNode node = index.byId.get(id);
        return node == null ? "#" + id : node.name();
    }

    /** 返回分类从根到自身的路径，如「工作/开发工具」。 */
    private String pathOf(FolderIndex index, Long id) {
        List<String> parts = new ArrayList<>();
        Long cur = id;
        while (cur != null) {
            WebsiteViews.FolderNode node = index.byId.get(cur);
            if (node == null) {
                break;
            }
            parts.add(0, node.name());
            cur = node.parentId();
        }
        return String.join("/", parts);
    }

    /**
     * 解析「分类 #id 或分类名」引用；根目录类说法（未分类/无/根目录）返回 null。
     * 找不到或同名歧义时抛出带提示的 {@link ResponseStatusException}。
     */
    private Long resolveFolderId(FolderIndex index, String ref) {
        String clean = ref.trim();
        Long parsed = parseId(clean);
        if (parsed != null) {
            if (index.byId.containsKey(parsed)) {
                return parsed;
            }
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST,
                    "分类不存在：#" + parsed + "，请先用 listSiteFolders 查看现有分类。");
        }
        if (isRootToken(clean)) {
            return null;
        }
        List<Long> ids = idsByFolderName(index, clean);
        if (ids.isEmpty()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST,
                    "未找到名为「" + clean + "」的分类（现有分类：" + existingFoldersLine(index)
                            + "）。请先询问用户是新建该分类还是放入含义相近的现有分类。");
        }
        if (ids.size() > 1) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, ambiguousFoldersMessage(index, ids));
        }
        return ids.get(0);
    }

    private WebsiteViews.BookmarkView resolveBookmark(
            FolderIndex index, WebsiteViews.Library lib, String ref) {
        String clean = ref.trim();
        Long parsed = parseId(clean);
        if (parsed != null) {
            for (WebsiteViews.BookmarkView b : lib.bookmarks()) {
                if (b.id().equals(parsed)) {
                    return b;
                }
            }
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST,
                    "没有找到网站 #" + parsed + "，请先用 listSiteBookmarks 确认 #id。");
        }
        // 网址匹配：尝试按完整网址精确比较（忽略大小写）。
        String urlCandidate = null;
        if (clean.contains("://") || (!clean.contains(" ") && clean.contains("."))) {
            try {
                urlCandidate = service.normalizeUrl(clean);
            }
            catch (ResponseStatusException ignored) {
                urlCandidate = null;
            }
        }
        List<WebsiteViews.BookmarkView> urlMatches = new ArrayList<>();
        List<WebsiteViews.BookmarkView> nameMatches = new ArrayList<>();
        for (WebsiteViews.BookmarkView b : lib.bookmarks()) {
            if (urlCandidate != null && b.url().equalsIgnoreCase(urlCandidate)) {
                urlMatches.add(b);
            }
            if (b.name().trim().equalsIgnoreCase(clean)) {
                nameMatches.add(b);
            }
        }
        if (urlMatches.size() == 1) {
            return urlMatches.get(0);
        }
        if (urlMatches.size() > 1) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST,
                    "该网址对应多条记录：" + bookmarkIdsText(urlMatches)
                            + "，请让用户按 #id 指定。");
        }
        if (nameMatches.size() == 1) {
            return nameMatches.get(0);
        }
        if (nameMatches.size() > 1) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST,
                    "同名网站有多个：" + bookmarkIdsText(nameMatches)
                            + "，请让用户按 #id 指定。");
        }
        throw new ResponseStatusException(HttpStatus.BAD_REQUEST,
                "没有找到「" + clean + "」对应的网站，请先用 listSiteBookmarks 查询确认 #id。");
    }

    private String bookmarkIdsText(List<WebsiteViews.BookmarkView> list) {
        List<String> parts = new ArrayList<>();
        for (WebsiteViews.BookmarkView b : list) {
            parts.add("#" + b.id() + " " + b.name());
        }
        return String.join("、", parts);
    }

    /** 识别 "#12" 或纯数字。 */
    private Long parseId(String text) {
        String value = text.startsWith("#") ? text.substring(1) : text;
        if (value.isEmpty()) {
            return null;
        }
        for (int i = 0; i < value.length(); i++) {
            if (!Character.isDigit(value.charAt(i))) {
                return null;
            }
        }
        try {
            return Long.parseLong(value);
        }
        catch (NumberFormatException e) {
            return null;
        }
    }

    private boolean isRootToken(String text) {
        String value = text.trim().toLowerCase();
        return value.equals("未分类") || value.equals("无") || value.equals("无分类")
                || value.equals("根目录") || value.equals("root");
    }

    private String clean(String value) {
        if (value == null || value.isBlank()) {
            return null;
        }
        return value.trim();
    }

    /** 名称缺省时取网址域名（去掉 www. 前缀）。 */
    private String defaultName(String normalizedUrl) {
        try {
            URI uri = new URI(normalizedUrl);
            String host = uri.getHost();
            if (host == null || host.isBlank()) {
                return normalizedUrl;
            }
            return host.startsWith("www.") ? host.substring(4) : host;
        }
        catch (Exception e) {
            return normalizedUrl;
        }
    }

    private String reason(ResponseStatusException e) {
        return e.getReason() == null || e.getReason().isBlank()
                ? e.getMessage()
                : e.getReason();
    }

    /** 分类扁平索引。 */
    private static final class FolderIndex {
        final Map<Long, WebsiteViews.FolderNode> byId = new HashMap<>();
    }
}

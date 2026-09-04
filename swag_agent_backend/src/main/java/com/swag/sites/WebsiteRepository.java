package com.swag.sites;

import org.springframework.jdbc.core.RowMapper;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.jdbc.support.GeneratedKeyHolder;
import org.springframework.jdbc.support.KeyHolder;
import org.springframework.stereotype.Repository;

import java.sql.Timestamp;
import java.time.LocalDateTime;
import java.util.List;
import java.util.Optional;

/**
 * 常用网站文件夹与书签的 JDBC 访问。
 */
@Repository
public class WebsiteRepository {

    private static final String FOLDER_COLUMNS =
            "id, user_id, name, parent_id, sort_order, created_at, updated_at";

    private static final String BOOKMARK_COLUMNS =
            "id, user_id, folder_id, name, url, description, icon_url, sort_order,"
                    + " created_at, updated_at";

    private final NamedParameterJdbcTemplate jdbc;

    public WebsiteRepository(NamedParameterJdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    private static final RowMapper<WebsiteFolderDO> FOLDER_MAPPER = (rs, i) -> {
        WebsiteFolderDO folder = new WebsiteFolderDO();
        folder.setId(rs.getLong("id"));
        folder.setUserId(rs.getLong("user_id"));
        folder.setName(rs.getString("name"));
        long parentId = rs.getLong("parent_id");
        folder.setParentId(rs.wasNull() ? null : parentId);
        folder.setSortOrder(rs.getInt("sort_order"));
        folder.setCreatedAt(rs.getTimestamp("created_at").toLocalDateTime());
        folder.setUpdatedAt(rs.getTimestamp("updated_at").toLocalDateTime());
        return folder;
    };

    private static final RowMapper<WebsiteBookmarkDO> BOOKMARK_MAPPER = (rs, i) -> {
        WebsiteBookmarkDO bookmark = new WebsiteBookmarkDO();
        bookmark.setId(rs.getLong("id"));
        bookmark.setUserId(rs.getLong("user_id"));
        long folderId = rs.getLong("folder_id");
        bookmark.setFolderId(rs.wasNull() ? null : folderId);
        bookmark.setName(rs.getString("name"));
        bookmark.setUrl(rs.getString("url"));
        bookmark.setDescription(rs.getString("description"));
        bookmark.setIconUrl(rs.getString("icon_url"));
        bookmark.setSortOrder(rs.getInt("sort_order"));
        bookmark.setCreatedAt(rs.getTimestamp("created_at").toLocalDateTime());
        bookmark.setUpdatedAt(rs.getTimestamp("updated_at").toLocalDateTime());
        return bookmark;
    };

    public List<WebsiteFolderDO> listFolders(Long userId) {
        return jdbc.query(
                "SELECT " + FOLDER_COLUMNS + " FROM website_folder"
                        + " WHERE user_id = :userId ORDER BY sort_order, id",
                new MapSqlParameterSource("userId", userId),
                FOLDER_MAPPER);
    }

    public Optional<WebsiteFolderDO> findFolderById(Long id) {
        List<WebsiteFolderDO> list = jdbc.query(
                "SELECT " + FOLDER_COLUMNS + " FROM website_folder WHERE id = :id",
                new MapSqlParameterSource("id", id),
                FOLDER_MAPPER);
        return list.stream().findFirst();
    }

    public WebsiteFolderDO insertFolder(WebsiteFolderDO folder) {
        KeyHolder keyHolder = new GeneratedKeyHolder();
        jdbc.update("""
                        INSERT INTO website_folder
                            (user_id, name, parent_id, sort_order, created_at, updated_at)
                        VALUES
                            (:userId, :name, :parentId, :sortOrder, :createdAt, :updatedAt)
                        """,
                folderParams(folder),
                keyHolder,
                new String[]{"id"});
        folder.setId(keyHolder.getKey().longValue());
        return folder;
    }

    public void updateFolder(Long id, Long userId, String name, Long parentId,
                             LocalDateTime updatedAt) {
        jdbc.update("""
                        UPDATE website_folder
                        SET name = :name, parent_id = :parentId, updated_at = :updatedAt
                        WHERE id = :id AND user_id = :userId
                        """,
                new MapSqlParameterSource()
                        .addValue("id", id)
                        .addValue("userId", userId)
                        .addValue("name", name)
                        .addValue("parentId", parentId)
                        .addValue("updatedAt", Timestamp.valueOf(updatedAt)));
    }

    public void deleteFolders(List<Long> ids, Long userId) {
        if (ids == null || ids.isEmpty()) {
            return;
        }
        jdbc.update("DELETE FROM website_folder WHERE id IN (:ids) AND user_id = :userId",
                new MapSqlParameterSource()
                        .addValue("ids", ids)
                        .addValue("userId", userId));
    }

    public List<WebsiteBookmarkDO> listBookmarks(Long userId, Long folderId, String query,
                                                 boolean unclassifiedOnly) {
        StringBuilder sql = new StringBuilder("SELECT " + BOOKMARK_COLUMNS
                + " FROM website_bookmark WHERE user_id = :userId");
        MapSqlParameterSource params = new MapSqlParameterSource("userId", userId);
        if (unclassifiedOnly) {
            sql.append(" AND folder_id IS NULL");
        }
        else if (folderId != null) {
            sql.append(" AND folder_id = :folderId");
            params.addValue("folderId", folderId);
        }
        if (query != null && !query.isBlank()) {
            sql.append(" AND (LOWER(name) LIKE LOWER(:q) OR LOWER(url) LIKE LOWER(:q)"
                    + " OR LOWER(COALESCE(description, '')) LIKE LOWER(:q))");
            params.addValue("q", "%" + query.trim() + "%");
        }
        sql.append(" ORDER BY sort_order, id");
        return jdbc.query(sql.toString(), params, BOOKMARK_MAPPER);
    }

    public Optional<WebsiteBookmarkDO> findBookmarkById(Long id) {
        List<WebsiteBookmarkDO> list = jdbc.query(
                "SELECT " + BOOKMARK_COLUMNS + " FROM website_bookmark WHERE id = :id",
                new MapSqlParameterSource("id", id),
                BOOKMARK_MAPPER);
        return list.stream().findFirst();
    }

    /** Binary icon cache is deliberately read separately so normal bookmark lists stay small. */
    public Optional<CachedIcon> findCachedIcon(Long id, Long userId) {
        List<CachedIcon> list = jdbc.query("""
                        SELECT icon_data, icon_content_type FROM website_bookmark
                        WHERE id = :id AND user_id = :userId AND icon_data IS NOT NULL
                        """,
                new MapSqlParameterSource().addValue("id", id).addValue("userId", userId),
                (rs, i) -> new CachedIcon(rs.getBytes("icon_data"), rs.getString("icon_content_type")));
        return list.stream().findFirst();
    }

    public void storeCachedIcon(Long id, Long userId, byte[] data, String contentType,
                                LocalDateTime updatedAt) {
        jdbc.update("""
                        UPDATE website_bookmark
                        SET icon_data = :data, icon_content_type = :contentType, updated_at = :updatedAt
                        WHERE id = :id AND user_id = :userId
                        """,
                new MapSqlParameterSource()
                        .addValue("id", id)
                        .addValue("userId", userId)
                        .addValue("data", data)
                        .addValue("contentType", contentType)
                        .addValue("updatedAt", Timestamp.valueOf(updatedAt)));
    }

    public void clearCachedIcon(Long id, Long userId, LocalDateTime updatedAt) {
        jdbc.update("""
                        UPDATE website_bookmark
                        SET icon_data = NULL, icon_content_type = NULL, updated_at = :updatedAt
                        WHERE id = :id AND user_id = :userId
                        """,
                new MapSqlParameterSource()
                        .addValue("id", id)
                        .addValue("userId", userId)
                        .addValue("updatedAt", Timestamp.valueOf(updatedAt)));
    }

    public WebsiteBookmarkDO insertBookmark(WebsiteBookmarkDO bookmark) {
        KeyHolder keyHolder = new GeneratedKeyHolder();
        jdbc.update("""
                        INSERT INTO website_bookmark
                            (user_id, folder_id, name, url, description, icon_url,
                             sort_order, created_at, updated_at)
                        VALUES
                            (:userId, :folderId, :name, :url, :description, :iconUrl,
                             :sortOrder, :createdAt, :updatedAt)
                        """,
                bookmarkParams(bookmark),
                keyHolder,
                new String[]{"id"});
        bookmark.setId(keyHolder.getKey().longValue());
        return bookmark;
    }

    public void updateBookmark(Long id, Long userId, String name, String url,
                               String description, String iconUrl, Long folderId,
                               LocalDateTime updatedAt) {
        jdbc.update("""
                        UPDATE website_bookmark
                        SET name = :name, url = :url, description = :description,
                            icon_url = :iconUrl, folder_id = :folderId, updated_at = :updatedAt
                        WHERE id = :id AND user_id = :userId
                        """,
                new MapSqlParameterSource()
                        .addValue("id", id)
                        .addValue("userId", userId)
                        .addValue("name", name)
                        .addValue("url", url)
                        .addValue("description", description)
                        .addValue("iconUrl", iconUrl)
                        .addValue("folderId", folderId)
                        .addValue("updatedAt", Timestamp.valueOf(updatedAt)));
    }

    public void deleteBookmark(Long id, Long userId) {
        jdbc.update("DELETE FROM website_bookmark WHERE id = :id AND user_id = :userId",
                new MapSqlParameterSource().addValue("id", id).addValue("userId", userId));
    }

    public void deleteBookmarksByFolders(List<Long> folderIds, Long userId) {
        if (folderIds == null || folderIds.isEmpty()) {
            return;
        }
        jdbc.update("DELETE FROM website_bookmark WHERE folder_id IN (:ids) AND user_id = :userId",
                new MapSqlParameterSource()
                        .addValue("ids", folderIds)
                        .addValue("userId", userId));
    }

    private MapSqlParameterSource folderParams(WebsiteFolderDO folder) {
        return new MapSqlParameterSource()
                .addValue("userId", folder.getUserId())
                .addValue("name", folder.getName())
                .addValue("parentId", folder.getParentId())
                .addValue("sortOrder", folder.getSortOrder())
                .addValue("createdAt", Timestamp.valueOf(folder.getCreatedAt()))
                .addValue("updatedAt", Timestamp.valueOf(folder.getUpdatedAt()));
    }

    private MapSqlParameterSource bookmarkParams(WebsiteBookmarkDO bookmark) {
        return new MapSqlParameterSource()
                .addValue("userId", bookmark.getUserId())
                .addValue("folderId", bookmark.getFolderId())
                .addValue("name", bookmark.getName())
                .addValue("url", bookmark.getUrl())
                .addValue("description", bookmark.getDescription())
                .addValue("iconUrl", bookmark.getIconUrl())
                .addValue("sortOrder", bookmark.getSortOrder())
                .addValue("createdAt", Timestamp.valueOf(bookmark.getCreatedAt()))
                .addValue("updatedAt", Timestamp.valueOf(bookmark.getUpdatedAt()));
    }

    public record CachedIcon(byte[] data, String contentType) {
    }
}

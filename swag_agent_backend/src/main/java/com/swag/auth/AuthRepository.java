package com.swag.auth;

import org.springframework.jdbc.core.RowMapper;
import org.springframework.jdbc.core.namedparam.MapSqlParameterSource;
import org.springframework.jdbc.core.namedparam.NamedParameterJdbcTemplate;
import org.springframework.jdbc.support.GeneratedKeyHolder;
import org.springframework.jdbc.support.KeyHolder;
import org.springframework.stereotype.Repository;

import java.sql.Timestamp;
import java.util.List;
import java.util.Optional;

/**
 * 用户与登录令牌的 JDBC 访问。
 */
@Repository
public class AuthRepository {

    private final NamedParameterJdbcTemplate jdbc;

    public AuthRepository(NamedParameterJdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    private static final String USER_COLUMNS =
            "id, username, password_hash, display_name, role, created_at";

    private static final RowMapper<AppUserDO> USER_MAPPER = (rs, i) -> {
        AppUserDO user = new AppUserDO();
        user.setId(rs.getLong("id"));
        user.setUsername(rs.getString("username"));
        user.setPasswordHash(rs.getString("password_hash"));
        user.setDisplayName(rs.getString("display_name"));
        user.setRole(rs.getString("role"));
        user.setCreatedAt(rs.getTimestamp("created_at").toLocalDateTime());
        return user;
    };

    private static final RowMapper<AuthTokenDO> TOKEN_MAPPER = (rs, i) -> {
        AuthTokenDO token = new AuthTokenDO();
        token.setToken(rs.getString("token"));
        token.setUserId(rs.getLong("user_id"));
        token.setExpiresAt(rs.getTimestamp("expires_at").toLocalDateTime());
        token.setCreatedAt(rs.getTimestamp("created_at").toLocalDateTime());
        return token;
    };

    public Optional<AppUserDO> findByUsername(String username) {
        List<AppUserDO> list = jdbc.query(
                "SELECT " + USER_COLUMNS + " FROM app_user WHERE username = :username",
                new MapSqlParameterSource("username", username),
                USER_MAPPER);
        return list.stream().findFirst();
    }

    public Optional<AppUserDO> findById(Long id) {
        List<AppUserDO> list = jdbc.query(
                "SELECT " + USER_COLUMNS + " FROM app_user WHERE id = :id",
                new MapSqlParameterSource("id", id),
                USER_MAPPER);
        return list.stream().findFirst();
    }

    public List<AppUserDO> findAllOrderByCreatedDesc() {
        return jdbc.query(
                "SELECT " + USER_COLUMNS + " FROM app_user ORDER BY created_at DESC, id DESC",
                USER_MAPPER);
    }

    public AppUserDO insert(AppUserDO user) {
        KeyHolder keyHolder = new GeneratedKeyHolder();
        jdbc.update("""
                        INSERT INTO app_user (username, password_hash, display_name, role, created_at)
                        VALUES (:username, :passwordHash, :displayName, :role, :createdAt)
                        """,
                new MapSqlParameterSource()
                        .addValue("username", user.getUsername())
                        .addValue("passwordHash", user.getPasswordHash())
                        .addValue("displayName", user.getDisplayName())
                        .addValue("role", user.getRole())
                        .addValue("createdAt", Timestamp.valueOf(user.getCreatedAt())),
                keyHolder,
                new String[]{"id"});
        user.setId(keyHolder.getKey().longValue());
        return user;
    }

    public void updateRole(Long id, String role) {
        jdbc.update("UPDATE app_user SET role = :role WHERE id = :id",
                new MapSqlParameterSource()
                        .addValue("role", role)
                        .addValue("id", id));
    }

    public long countAdmins() {
        Long count = jdbc.queryForObject(
                "SELECT COUNT(*) FROM app_user WHERE role = 'ADMIN'",
                new MapSqlParameterSource(),
                Long.class);
        return count == null ? 0 : count;
    }

    public void insertToken(AuthTokenDO token) {
        jdbc.update("""
                        INSERT INTO auth_token (token, user_id, expires_at, created_at)
                        VALUES (:token, :userId, :expiresAt, :createdAt)
                        """,
                new MapSqlParameterSource()
                        .addValue("token", token.getToken())
                        .addValue("userId", token.getUserId())
                        .addValue("expiresAt", Timestamp.valueOf(token.getExpiresAt()))
                        .addValue("createdAt", Timestamp.valueOf(token.getCreatedAt())));
    }

    public Optional<AuthTokenDO> findByToken(String token) {
        List<AuthTokenDO> list = jdbc.query(
                "SELECT token, user_id, expires_at, created_at"
                        + " FROM auth_token WHERE token = :token",
                new MapSqlParameterSource("token", token),
                TOKEN_MAPPER);
        return list.stream().findFirst();
    }

    public void deleteToken(String token) {
        jdbc.update("DELETE FROM auth_token WHERE token = :token",
                new MapSqlParameterSource("token", token));
    }
}

-- 用户体系与登录令牌。
CREATE TABLE app_user (
    id            BIGINT       NOT NULL AUTO_INCREMENT,
    username      VARCHAR(64)  NOT NULL,
    password_hash VARCHAR(128) NOT NULL,
    display_name  VARCHAR(64)  NULL,
    created_at    DATETIME(6)  NOT NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_app_user_username (username)
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4;

CREATE TABLE auth_token (
    token      CHAR(36)    NOT NULL,
    user_id    BIGINT      NOT NULL,
    expires_at DATETIME(6) NOT NULL,
    created_at DATETIME(6) NOT NULL,
    PRIMARY KEY (token),
    KEY idx_auth_token_user (user_id)
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4;

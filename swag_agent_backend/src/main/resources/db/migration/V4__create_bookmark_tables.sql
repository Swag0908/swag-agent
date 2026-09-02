-- 常用网站：支持无限级文件夹树与网站书签。
CREATE TABLE website_folder (
    id         BIGINT      NOT NULL AUTO_INCREMENT,
    user_id    BIGINT      NOT NULL,
    name       VARCHAR(64) NOT NULL,
    parent_id  BIGINT      NULL,
    sort_order INT         NOT NULL DEFAULT 0,
    created_at DATETIME(6) NOT NULL,
    updated_at DATETIME(6) NOT NULL,
    PRIMARY KEY (id),
    KEY idx_folder_user_parent (user_id, parent_id),
    KEY idx_folder_user_created (user_id, created_at)
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4;

CREATE TABLE website_bookmark (
    id          BIGINT        NOT NULL AUTO_INCREMENT,
    user_id     BIGINT        NOT NULL,
    folder_id   BIGINT        NULL,
    name        VARCHAR(128)  NOT NULL,
    url         VARCHAR(1024) NOT NULL,
    description VARCHAR(512)  NULL,
    icon_url    VARCHAR(1024) NULL,
    sort_order  INT           NOT NULL DEFAULT 0,
    created_at  DATETIME(6)   NOT NULL,
    updated_at  DATETIME(6)   NOT NULL,
    PRIMARY KEY (id),
    KEY idx_bookmark_user_folder (user_id, folder_id),
    KEY idx_bookmark_user_created (user_id, created_at)
) ENGINE = InnoDB
  DEFAULT CHARSET = utf8mb4;

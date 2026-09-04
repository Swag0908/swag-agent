ALTER TABLE website_bookmark
    ADD COLUMN icon_data MEDIUMBLOB NULL,
    ADD COLUMN icon_content_type VARCHAR(100) NULL;

"""全局配置：与 Java application.properties / application-dev.properties 对齐。

真实密钥只从环境变量或本地 .env 读取，不写入仓库。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from urllib.parse import quote_plus

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---- 基础 ----
    app_name: str = "swag_agent"
    env: str = "dev"
    enable_docs: bool = False
    log_level: str = "INFO"

    # ---- DeepSeek / Agent ----
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model_flash: str = "deepseek-v4-flash"
    deepseek_model_pro: str = "deepseek-v4-pro"
    llm_timeout_s: int = 120
    max_tool_rounds: int = 8
    # None = 不显式传 thinking（跟随服务端默认）；"enabled"/"disabled" 对应 DeepSeek thinking.type
    thinking_mode: str | None = None

    # ---- 检索 ----
    tavily_api_key: str = ""
    tavily_url: str = "https://api.tavily.com/search"

    # ---- MySQL ----
    mysql_host: str = "127.0.0.1"
    mysql_port: int = 3306
    mysql_db: str = "swag_ai_agent"
    mysql_user: str = "root"
    mysql_password: str = ""

    # ---- PostgreSQL / pgvector ----
    pg_host: str = "127.0.0.1"
    pg_port: int = 5432
    pg_db: str = "postgres"
    pg_user: str = "postgres"
    pg_password: str = ""
    embedding_dimensions: int = 768

    # ---- Ollama ----
    ollama_base_url: str = "http://localhost:11434"
    ollama_embed_model: str = "nomic-embed-text"

    # ---- 认证 ----
    auth_admin_usernames: str = "swag"
    auth_admin_password: str = ""  # 仅 bootstrap 用；为空时跳过管理员种子（生产用环境变量提供）
    token_ttl_days: int = 7
    zipkin_cookie_name: str = "swag_zipkin_token"
    zipkin_cookie_path: str = "/zipkin"
    zipkin_cookie_secure: bool = False

    # ---- 技能包 ----
    skills_external_root: str = "./skills-data"
    skills_auto_inject: bool = True
    skills_max_body_chars: int = 20000
    skills_install_enabled: bool = True
    skills_install_timeout_seconds: int = 60

    # ---- 笔记 ----
    notes_root: str = "./notes-data"
    notes_import_roots: str = ""
    notes_max_markdown_bytes: int = 2 * 1024 * 1024
    notes_max_attachment_bytes: int = 20 * 1024 * 1024
    notes_max_import_total_bytes: int = 100 * 1024 * 1024
    notes_trash_retention_days: int = 7

    # ---- 审计 ----
    audit_enabled: bool = True
    audit_include_tool_content: bool = False
    audit_confirmation_ttl_seconds: int = 600
    audit_confirmation_required_tools: str = ""
    audit_zipkin_ui_base_url: str = ""

    # ---- 运行开关 ----
    scheduler_enabled: bool = False
    dual_write_chat_memory: bool = False
    bootstrap_on_startup: bool = True

    # ---- 派生属性 ----
    @property
    def mysql_url(self) -> str:
        user = quote_plus(self.mysql_user)
        password = quote_plus(self.mysql_password)
        return (
            f"mysql+pymysql://{user}:{password}@{self.mysql_host}:{self.mysql_port}/"
            f"{self.mysql_db}?charset=utf8mb4"
        )

    @property
    def pg_url(self) -> str:
        user = quote_plus(self.pg_user)
        password = quote_plus(self.pg_password)
        return f"postgresql+psycopg://{user}:{password}@{self.pg_host}:{self.pg_port}/{self.pg_db}"

    @property
    def admin_usernames(self) -> list[str]:
        return [x.strip() for x in self.auth_admin_usernames.split(",") if x.strip()]

    @property
    def confirmation_required_tools(self) -> set[str]:
        return {x.strip() for x in self.audit_confirmation_required_tools.split(",") if x.strip()}

    @property
    def import_roots(self) -> list[Path]:
        roots: list[Path] = []
        for raw in self.notes_import_roots.split(","):
            raw = raw.strip()
            if raw:
                roots.append(Path(raw).expanduser().resolve())
        return roots

    @property
    def notes_root_path(self) -> Path:
        return Path(self.notes_root).expanduser().resolve()

    @property
    def skills_root_path(self) -> Path:
        return Path(self.skills_external_root).expanduser().resolve()


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

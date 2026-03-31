"""Application configuration loaded from environment variables."""

from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    # Database
    database_url: str = "postgresql+asyncpg://seo_user:seo_pass@localhost:5432/seo_crawler"
    database_url_sync: str = "postgresql+psycopg2://seo_user:seo_pass@localhost:5432/seo_crawler"

    # Redis
    redis_url: str = "redis://localhost:6379/0"

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_secret_key: str = "change-me-in-production"

    # Crawler defaults
    default_max_pages: int = 10000
    default_max_depth: int = 50
    default_rate_limit_rps: float = 2.0
    default_concurrency: int = 5
    default_render_cap: int = 500
    default_user_agent: str = "SEOCrawler/1.0 (+https://example.com/bot)"

    # Playwright
    playwright_timeout_ms: int = 30000
    playwright_max_workers: int = 3

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()

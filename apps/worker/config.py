from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    app_env: str = "development"
    database_url: str
    redis_url: str
    litellm_base_url: str
    litellm_api_key: str
    sentry_dsn: str = ""
    worker_concurrency: int = 5
    worker_queue_poll_interval: float = 2.0

    # Scraping safety — keep conservative to avoid platform blocks
    scraping_strict_mode: bool = True
    scraping_linkedin_use_playwright: bool = False
    scraping_linkedin_max_direct_per_scan: int = 3
    scraping_threads_max_direct_per_scan: int = 5
    # Never enable unless you accept account ban risk on Upwork/LinkedIn etc.
    scraping_allow_authenticated_sources: bool = False

    # Comment posting — API auto-post only for platforms with official APIs
    comment_auto_post_reddit: bool = False
    comment_auto_post_devto: bool = False
    reddit_client_id: str = ""
    reddit_client_secret: str = ""
    reddit_refresh_token: str = ""
    reddit_user_agent: str = "ProspectOS/1.0 (lead engagement)"
    devto_api_key: str = ""
    github_token: str = ""

    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


settings = Settings()

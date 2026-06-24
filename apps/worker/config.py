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

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()

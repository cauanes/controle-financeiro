from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file="../.env", extra="ignore")
    database_url: str = "postgresql://finance_app:change-me@localhost:5432/finance"
    redis_url: str = "redis://localhost:6379/0"
    environment: str = "development"
    allowed_origins: str = "http://localhost:5173,http://localhost:8080"
    cookie_secure: bool = False
    storage_dir: str = "../.local/uploads"
    evolution_base_url: str = ""
    evolution_api_key: str = ""
    evolution_webhook_secret: str = ""
    transcription_url: str = ""
    transcription_api_key: str = ""
    transcription_model: str = ""
    searxng_url: str = ""

    def validate_runtime(self):
        if self.environment == "production" and not self.cookie_secure:
            raise ValueError("COOKIE_SECURE must be true in production")


settings = Settings()

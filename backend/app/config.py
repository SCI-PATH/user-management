from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "SCI-PATH User Management"
    # SQLite for zero-config local; set DATABASE_URL for PostgreSQL
    # e.g. postgresql+psycopg2://postgres:password@localhost:5432/scipath_users
    database_url: str = "sqlite:///./data/users.db"

    jwt_secret: str = "change-me-in-production-use-long-random-string"
    jwt_algorithm: str = "HS256"
    # Sessions max 6 hours
    access_token_expire_minutes: int = 360
    # Password-reset tokens
    password_reset_expire_minutes: int = 60
    # When true (default for local/dev), forgot-password response includes reset_token
    # so you can test without email. Set false in production and wire SMTP later.
    expose_reset_token: bool = True

    cors_origins: str = "http://localhost:3000,http://localhost:3001,http://127.0.0.1:3000,http://127.0.0.1:3001"

    # Optional Google OAuth (leave empty to hide until configured)
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://127.0.0.1:8001/auth/google/callback"

    # Where to send browser after OAuth success (frontend with token in hash/query)
    oauth_success_redirect: str = "http://127.0.0.1:3001/auth/callback"


@lru_cache
def get_settings() -> Settings:
    return Settings()

"""Settings, read from the environment and from bff/.env.

Environment variables win over the .env file, which is what lets the tests
override values without touching your real .env.
"""

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Signs the oauth_pending cookie (WORKFLOW.md step 1 and 4).
    secret_key: str = Field(min_length=32)
    # Fernet key; encrypts tokens in the sessions table (step 7).
    token_enc_key: str

    database_url: str

    frontend_origin: str = "http://localhost:3000"
    bff_origin: str = "http://localhost:8000"

    google_client_id: str = ""
    google_client_secret: str = ""

    # Lifetimes. The pending cookie covers steps 1 to 4; the session covers everything after 8.
    pending_login_seconds: int = 600
    session_days: int = 30


@lru_cache
def get_settings() -> Settings:
    return Settings()

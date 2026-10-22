from functools import cached_property
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import URL


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DKMAN_", extra="ignore")

    database_url: SecretStr | None = None
    db_host: str = "postgres"
    db_port: int = 5432
    db_name: str = "dkman"
    db_user: str = "dkman_core"
    db_password_file: Path = Path("/run/secrets/core-db-password")
    oidc_issuer: str = "http://localhost:8080/auth/realms/dkman"
    oidc_jwks_url: str = "http://keycloak:8080/auth/realms/dkman/protocol/openid-connect/certs"
    oidc_audience: str = "dkman-api"
    public_url: str = "http://localhost:8080"
    health_timeout_seconds: float = 3.0
    deployment_enabled: bool = False
    deployment_catalog_file: Path = Path("/etc/dkman-adapter/catalog.json")
    deployment_secret_file: Path = Path("/run/secrets/adapter-delegation-key")
    chat_provider: Literal["rules", "openai_compatible"] = "rules"
    chat_api_url: str = ""
    chat_model: str = Field(default="", max_length=120)
    chat_provider_label: str = Field(
        default="Konfigurierter Modellanbieter", min_length=1, max_length=80
    )
    chat_api_key_file: Path = Path("/run/secrets/chat-model-api-key")
    chat_timeout_seconds: float = Field(default=10, ge=1, le=20)

    @cached_property
    def sqlalchemy_url(self) -> str | URL:
        if self.database_url is not None:
            return self.database_url.get_secret_value()
        return URL.create(
            "postgresql+psycopg",
            username=self.db_user,
            password=self.db_password_file.read_text().strip(),
            host=self.db_host,
            port=self.db_port,
            database=self.db_name,
        )

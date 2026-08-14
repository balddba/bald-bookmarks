"""Application settings loaded from environment variables."""

import json
from pathlib import Path
from typing import Annotated
from urllib.parse import quote_plus

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    """Validated runtime configuration for Bald Bookmarks.

    Attributes:
        db_driver (str): Database driver name (oracle or memory).
        oracle_user (str | None): Oracle username.
        oracle_password (str | None): Oracle password.
        oracle_dsn (str | None): Oracle Easy Connect or TNS DSN.
        job_poll_seconds (float): Seconds between job poll cycles.
        job_max_attempts (int): Max attempts before a job is failed.
        media_root (Path): Root directory for thumbnail media files.
        cors_origins (list[str]): Allowed browser origins for CORS.
        thumbnail_viewport_width (int): Screenshot viewport width in pixels.
        thumbnail_viewport_height (int): Screenshot viewport height in pixels.
        thumbnail_timeout_ms (int): Page navigation timeout for previews.
        thumbnail_no_sandbox (bool): Launch Chromium without the sandbox.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="forbid",
        populate_by_name=True,
    )

    db_driver: str = Field(default="oracle", alias="DB_DRIVER")
    oracle_user: str | None = Field(default=None, alias="ORACLE_USER")
    oracle_password: str | None = Field(default=None, alias="ORACLE_PASSWORD")
    oracle_dsn: str | None = Field(default=None, alias="ORACLE_DSN")
    job_poll_seconds: float = Field(default=5.0, alias="JOB_POLL_SECONDS")
    job_max_attempts: int = Field(default=3, alias="JOB_MAX_ATTEMPTS")
    media_root: Path = Field(
        default=Path("backend/bald_bookmarks/media"),
        alias="MEDIA_ROOT",
    )
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173"],
        alias="CORS_ORIGINS",
    )
    thumbnail_viewport_width: int = Field(
        default=1280,
        alias="THUMBNAIL_VIEWPORT_WIDTH",
        ge=320,
        le=3840,
    )
    thumbnail_viewport_height: int = Field(
        default=720,
        alias="THUMBNAIL_VIEWPORT_HEIGHT",
        ge=240,
        le=2160,
    )
    thumbnail_timeout_ms: int = Field(
        default=20_000,
        alias="THUMBNAIL_TIMEOUT_MS",
        ge=1_000,
        le=120_000,
    )
    thumbnail_no_sandbox: bool = Field(
        default=False,
        alias="THUMBNAIL_NO_SANDBOX",
    )

    @field_validator("cors_origins", mode="before")
    @classmethod
    def split_cors_origins(cls, value: object) -> object:
        """Parse comma-separated or JSON-list CORS origins.

        Args:
            value (object): Raw settings value.

        Returns:
            object: List of origins or the original value.
        """
        if isinstance(value, str):
            stripped = value.strip()
            if stripped.startswith("["):
                return json.loads(stripped)
            return [part.strip() for part in stripped.split(",") if part.strip()]
        return value

    @model_validator(mode="after")
    def require_oracle_when_needed(self) -> "Settings":
        """Fail fast when Oracle credentials are missing for the oracle driver.

        Returns:
            Settings: Validated settings.

        Raises:
            ValueError: If oracle driver lacks required connection fields.
        """
        if self.db_driver.strip().lower() == "oracle":
            missing = [
                name
                for name, value in (
                    ("ORACLE_USER", self.oracle_user),
                    ("ORACLE_PASSWORD", self.oracle_password),
                    ("ORACLE_DSN", self.oracle_dsn),
                )
                if not value
            ]
            if missing:
                raise ValueError(
                    "Oracle driver requires settings: " + ", ".join(missing)
                )
        return self

    def oracle_connect_args(self) -> dict[str, str]:
        """Return oracledb.connect kwargs matching OracleDriver.

        Returns:
            dict[str, str]: user, password, and Easy Connect or TNS dsn.

        Raises:
            ValueError: If Oracle connection settings are incomplete.
        """
        if not self.oracle_user or not self.oracle_password or not self.oracle_dsn:
            raise ValueError("Oracle connection settings are required for Alembic")
        return {
            "user": self.oracle_user,
            "password": self.oracle_password,
            "dsn": self.oracle_dsn,
        }

    @property
    def sqlalchemy_url(self) -> str:
        """Build the SQLAlchemy URL used by Alembic offline mode.

        Easy Connect values of the form host:port/service are emitted as a
        service_name query parameter. SQLAlchemy otherwise treats the path as a SID.

        Returns:
            str: Oracle SQLAlchemy URL with oracledb driver.

        Raises:
            ValueError: If Oracle connection settings are incomplete.
        """
        args = self.oracle_connect_args()
        user = quote_plus(args["user"])
        password = quote_plus(args["password"])
        dsn = args["dsn"].strip()
        if dsn.startswith("("):
            return f"oracle+oracledb://{user}:{password}/?dsn={quote_plus(dsn)}"
        slash = dsn.find("/")
        if slash != -1:
            hostport = dsn[:slash]
            service = dsn[slash + 1 :].split("?", 1)[0]
            return (
                f"oracle+oracledb://{user}:{password}@{hostport}/"
                f"?service_name={quote_plus(service)}"
            )
        return f"oracle+oracledb://{user}:{password}@{dsn}"

    @property
    def thumbnails_dir(self) -> Path:
        """Resolve the on-disk thumbnail directory.

        Returns:
            Path: Absolute path under media_root/thumbnails.
        """
        return Path(self.media_root) / "thumbnails"


def get_settings() -> Settings:
    """Load and validate application settings.

    Returns:
        Settings: Validated settings instance.
    """
    return Settings()

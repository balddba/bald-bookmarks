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
        db_driver (str): Database driver name (oracle, postgres, mysql, or sqlite).
        oracle_user (str | None): Oracle username.
        oracle_password (str | None): Oracle password.
        oracle_dsn (str | None): Oracle Easy Connect or TNS DSN.
        postgres_host (str | None): PostgreSQL hostname.
        postgres_port (int): PostgreSQL port.
        postgres_user (str | None): PostgreSQL username.
        postgres_password (str | None): PostgreSQL password.
        postgres_database (str | None): PostgreSQL database name.
        mysql_host (str | None): MySQL hostname.
        mysql_port (int): MySQL port.
        mysql_user (str | None): MySQL username.
        mysql_password (str | None): MySQL password.
        mysql_database (str | None): MySQL database name.
        sqlite_path (Path): Filesystem path to the SQLite database file.
        job_poll_seconds (float): Seconds between job poll cycles.
        job_max_attempts (int): Max attempts before a job is failed.
        media_root (Path): Root directory for thumbnail media files.
        cors_origins (list[str]): Allowed browser origins for CORS.
        thumbnail_viewport_width (int): Screenshot viewport width in pixels.
        thumbnail_viewport_height (int): Screenshot viewport height in pixels.
        thumbnail_timeout_ms (int): Page navigation timeout for previews.
        thumbnail_no_sandbox (bool): Launch Chromium without the sandbox.
        sentry_dsn (str): Sentry DSN; empty disables the SDK.
        sentry_environment (str): Sentry environment tag.
        sentry_traces_sample_rate (float): Trace sample rate without a parent decision.
        vite_sentry_dsn (str): Browser Sentry DSN from the shared env file.
        vite_sentry_environment (str): Browser Sentry environment tag.
        vite_sentry_traces_sample_rate (str): Browser trace sample rate.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="forbid",
        populate_by_name=True,
    )

    db_driver: str = Field(default="sqlite", alias="DB_DRIVER")
    oracle_user: str | None = Field(default=None, alias="ORACLE_USER")
    oracle_password: str | None = Field(default=None, alias="ORACLE_PASSWORD")
    oracle_dsn: str | None = Field(default=None, alias="ORACLE_DSN")
    postgres_host: str | None = Field(default=None, alias="POSTGRES_HOST")
    postgres_port: int = Field(default=5432, alias="POSTGRES_PORT", ge=1, le=65535)
    postgres_user: str | None = Field(default=None, alias="POSTGRES_USER")
    postgres_password: str | None = Field(default=None, alias="POSTGRES_PASSWORD")
    postgres_database: str | None = Field(default=None, alias="POSTGRES_DATABASE")
    mysql_host: str | None = Field(default=None, alias="MYSQL_HOST")
    mysql_port: int = Field(default=3306, alias="MYSQL_PORT", ge=1, le=65535)
    mysql_user: str | None = Field(default=None, alias="MYSQL_USER")
    mysql_password: str | None = Field(default=None, alias="MYSQL_PASSWORD")
    mysql_database: str | None = Field(default=None, alias="MYSQL_DATABASE")
    sqlite_path: Path = Field(
        default=Path("backend/bald_bookmarks/data/bookmarks.db"),
        alias="SQLITE_PATH",
    )
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
    sentry_dsn: str = Field(
        default="",
        alias="SENTRY_DSN",
    )
    sentry_environment: str = Field(
        default="development",
        alias="SENTRY_ENVIRONMENT",
    )
    sentry_traces_sample_rate: float = Field(
        default=1.0,
        alias="SENTRY_TRACES_SAMPLE_RATE",
        ge=0.0,
        le=1.0,
    )
    vite_sentry_dsn: str = Field(
        default="",
        alias="VITE_SENTRY_DSN",
    )
    vite_sentry_environment: str = Field(
        default="",
        alias="VITE_SENTRY_ENVIRONMENT",
    )
    vite_sentry_traces_sample_rate: str = Field(
        default="",
        alias="VITE_SENTRY_TRACES_SAMPLE_RATE",
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

    @property
    def normalized_driver(self) -> str:
        """Return the canonical driver name.

        Returns:
            str: Lowercased driver name with postgresql mapped to postgres.
        """
        name = self.db_driver.strip().lower()
        if name == "postgresql":
            return "postgres"
        return name

    @model_validator(mode="after")
    def require_credentials_when_needed(self) -> "Settings":
        """Fail fast when the selected driver is missing connection fields.

        Returns:
            Settings: Validated settings.

        Raises:
            ValueError: If the selected driver lacks required connection fields.
        """
        driver = self.normalized_driver
        if driver == "oracle":
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
        elif driver == "postgres":
            missing = [
                name
                for name, value in (
                    ("POSTGRES_HOST", self.postgres_host),
                    ("POSTGRES_USER", self.postgres_user),
                    ("POSTGRES_PASSWORD", self.postgres_password),
                    ("POSTGRES_DATABASE", self.postgres_database),
                )
                if not value
            ]
            if missing:
                raise ValueError(
                    "PostgreSQL driver requires settings: " + ", ".join(missing)
                )
        elif driver == "mysql":
            missing = [
                name
                for name, value in (
                    ("MYSQL_HOST", self.mysql_host),
                    ("MYSQL_USER", self.mysql_user),
                    ("MYSQL_PASSWORD", self.mysql_password),
                    ("MYSQL_DATABASE", self.mysql_database),
                )
                if not value
            ]
            if missing:
                raise ValueError(
                    "MySQL driver requires settings: " + ", ".join(missing)
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

    def postgres_connect_args(self) -> dict[str, str | int]:
        """Return PostgreSQL connection fields used by the driver and Alembic.

        Returns:
            dict[str, str | int]: host, port, user, password, and database.

        Raises:
            ValueError: If PostgreSQL connection settings are incomplete.
        """
        if (
            not self.postgres_host
            or not self.postgres_user
            or not self.postgres_password
            or not self.postgres_database
        ):
            raise ValueError("PostgreSQL connection settings are required for Alembic")
        return {
            "host": self.postgres_host,
            "port": self.postgres_port,
            "user": self.postgres_user,
            "password": self.postgres_password,
            "database": self.postgres_database,
        }

    def mysql_connect_args(self) -> dict[str, str | int]:
        """Return MySQL connection fields used by the driver and Alembic.

        Returns:
            dict[str, str | int]: host, port, user, password, and database.

        Raises:
            ValueError: If MySQL connection settings are incomplete.
        """
        if (
            not self.mysql_host
            or not self.mysql_user
            or not self.mysql_password
            or not self.mysql_database
        ):
            raise ValueError("MySQL connection settings are required for Alembic")
        return {
            "host": self.mysql_host,
            "port": self.mysql_port,
            "user": self.mysql_user,
            "password": self.mysql_password,
            "database": self.mysql_database,
        }

    def sqlite_db_path(self) -> Path:
        """Return the expanded SQLite database path.

        Returns:
            Path: Filesystem path to the SQLite file.
        """
        return Path(self.sqlite_path).expanduser()

    def _sqlite_sqlalchemy_url(self) -> str:
        """Build the SQLite SQLAlchemy URL used by Alembic.

        Returns:
            str: SQLite URL using the pysqlite driver.
        """
        path = self.sqlite_db_path()
        if not path.is_absolute():
            path = Path.cwd() / path
        return f"sqlite+pysqlite:///{path.as_posix()}"

    def _oracle_sqlalchemy_url(self) -> str:
        """Build the Oracle SQLAlchemy URL used by Alembic offline mode.

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

    def _postgres_sqlalchemy_url(self) -> str:
        """Build the PostgreSQL SQLAlchemy URL.

        Returns:
            str: PostgreSQL URL using the psycopg driver.

        Raises:
            ValueError: If PostgreSQL connection settings are incomplete.
        """
        args = self.postgres_connect_args()
        user = quote_plus(str(args["user"]))
        password = quote_plus(str(args["password"]))
        host = str(args["host"])
        database = quote_plus(str(args["database"]))
        return (
            f"postgresql+psycopg://{user}:{password}@{host}:{args['port']}/{database}"
        )

    def _mysql_sqlalchemy_url(self) -> str:
        """Build the MySQL SQLAlchemy URL.

        Returns:
            str: MySQL URL using the mysqlconnector driver.

        Raises:
            ValueError: If MySQL connection settings are incomplete.
        """
        args = self.mysql_connect_args()
        user = quote_plus(str(args["user"]))
        password = quote_plus(str(args["password"]))
        host = str(args["host"])
        database = quote_plus(str(args["database"]))
        return (
            f"mysql+mysqlconnector://{user}:{password}@{host}:{args['port']}/"
            f"{database}?charset=utf8mb4"
        )

    @property
    def sqlalchemy_url(self) -> str:
        """Build the SQLAlchemy URL used by Alembic for the selected driver.

        Runtime drivers use native DBAPI clients (oracledb, psycopg,
        mysql-connector, sqlite3). This URL is only for Alembic migrations.

        Returns:
            str: SQLAlchemy URL for Oracle, PostgreSQL, MySQL, or SQLite.

        Raises:
            ValueError: If required connection settings are incomplete.
        """
        driver = self.normalized_driver
        if driver == "postgres":
            return self._postgres_sqlalchemy_url()
        if driver == "mysql":
            return self._mysql_sqlalchemy_url()
        if driver == "sqlite":
            return self._sqlite_sqlalchemy_url()
        return self._oracle_sqlalchemy_url()

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

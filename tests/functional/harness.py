"""Start per-engine docker compose stacks for live database tests."""

from __future__ import annotations

import os
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from bald_bookmarks.config import Settings

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_DIR = REPO_ROOT / "compose"
PLACEHOLDER_PASSWORD = "changeme"
ORACLE_OPT_IN_ENV = "RUN_ORACLE_FUNCTIONAL"


class EngineSpec:
    """Describe how functional tests start and connect to one database.

    Attributes:
        name (str): Canonical driver name (sqlite, postgres, mysql, oracle).
        compose_file (str): Filename under compose/.
        wait_timeout_seconds (int): docker compose --wait-timeout in seconds.
        requires_opt_in (bool): True when an extra env flag is required.
        opt_in_env (str): Environment variable that enables this engine.
    """

    def __init__(
        self,
        name: str,
        compose_file: str,
        wait_timeout_seconds: int,
        *,
        requires_opt_in: bool = False,
        opt_in_env: str = "",
    ) -> None:
        """Store compose metadata for one engine.

        Args:
            name (str): Canonical driver name.
            compose_file (str): Filename under compose/.
            wait_timeout_seconds (int): docker compose --wait-timeout in seconds.
            requires_opt_in (bool): True when an extra env flag is required.
            opt_in_env (str): Environment variable that enables this engine.
        """
        self.name = name
        self.compose_file = compose_file
        self.wait_timeout_seconds = wait_timeout_seconds
        self.requires_opt_in = requires_opt_in
        self.opt_in_env = opt_in_env

    @property
    def compose_path(self) -> Path:
        """Return the absolute compose file path.

        Returns:
            Path: Compose file under the repository compose directory.
        """
        return COMPOSE_DIR / self.compose_file


ENGINE_SPECS: dict[str, EngineSpec] = {
    "sqlite": EngineSpec(
        name="sqlite",
        compose_file="sqlite.yml",
        wait_timeout_seconds=30,
    ),
    "postgres": EngineSpec(
        name="postgres",
        compose_file="postgres.yml",
        wait_timeout_seconds=120,
    ),
    "mysql": EngineSpec(
        name="mysql",
        compose_file="mysql.yml",
        wait_timeout_seconds=180,
    ),
    "oracle": EngineSpec(
        name="oracle",
        compose_file="oracle.yml",
        wait_timeout_seconds=600,
        requires_opt_in=True,
        opt_in_env=ORACLE_OPT_IN_ENV,
    ),
}


def compose_command(compose_file: Path, *args: str) -> list[str]:
    """Build a docker compose command for one stack file.

    Args:
        compose_file (Path): Compose YAML path.
        *args (str): Extra docker compose arguments.

    Returns:
        list[str]: Command argv.
    """
    return ["docker", "compose", "-f", str(compose_file), *args]


def compose_up_command(compose_file: Path, wait_timeout_seconds: int) -> list[str]:
    """Build `docker compose up --wait` for one stack.

    Args:
        compose_file (Path): Compose YAML path.
        wait_timeout_seconds (int): Seconds to wait for healthy services.

    Returns:
        list[str]: Command argv.
    """
    return compose_command(
        compose_file,
        "up",
        "-d",
        "--wait",
        "--wait-timeout",
        str(wait_timeout_seconds),
    )


def compose_down_command(compose_file: Path) -> list[str]:
    """Build `docker compose down -v` for one stack.

    Args:
        compose_file (Path): Compose YAML path.

    Returns:
        list[str]: Command argv.
    """
    return compose_command(compose_file, "down", "-v", "--remove-orphans")


def docker_available() -> bool:
    """Return whether the Docker daemon accepts commands.

    Returns:
        bool: True when `docker info` succeeds.
    """
    try:
        completed = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False
    return completed.returncode == 0


def opt_in_enabled(spec: EngineSpec) -> bool:
    """Return whether an opt-in engine should run.

    Args:
        spec (EngineSpec): Engine under test.

    Returns:
        bool: True when the engine has no flag or the flag is set to 1/true/yes.
    """
    if not spec.requires_opt_in:
        return True
    value = os.environ.get(spec.opt_in_env, "").strip().lower()
    return value in {"1", "true", "yes"}


def settings_for(engine: str, tmp_path: Path) -> Settings:
    """Build Settings for a live engine without reading `.env`.

    Args:
        engine (str): Canonical driver name.
        tmp_path (Path): Pytest temporary directory for files and media.

    Returns:
        Settings: Validated settings pointed at the compose-mapped database.

    Raises:
        KeyError: If `engine` is not a known functional-test engine.
    """
    media_root = tmp_path / "media"
    shared: dict[str, object] = {
        "job_poll_seconds": 60.0,
        "job_max_attempts": 3,
        "media_root": media_root,
    }
    if engine == "sqlite":
        return Settings(
            _env_file=None,
            db_driver="sqlite",
            sqlite_path=tmp_path / "bookmarks.db",
            **shared,
        )
    if engine == "postgres":
        return Settings(
            _env_file=None,
            db_driver="postgres",
            postgres_host="127.0.0.1",
            postgres_port=55432,
            postgres_user="bookmarks",
            postgres_password=PLACEHOLDER_PASSWORD,
            postgres_database="bald_bookmarks",
            **shared,
        )
    if engine == "mysql":
        return Settings(
            _env_file=None,
            db_driver="mysql",
            mysql_host="127.0.0.1",
            mysql_port=53306,
            mysql_user="bookmarks",
            mysql_password=PLACEHOLDER_PASSWORD,
            mysql_database="bald_bookmarks",
            **shared,
        )
    if engine == "oracle":
        return Settings(
            _env_file=None,
            db_driver="oracle",
            oracle_user="bookmarks",
            oracle_password=PLACEHOLDER_PASSWORD,
            oracle_dsn="127.0.0.1:51521/FREEPDB1",
            **shared,
        )
    raise KeyError(f"Unknown functional test engine: {engine}")


class ComposeStack:
    """Start and stop one database compose file."""

    def __init__(self, spec: EngineSpec) -> None:
        """Store the engine spec used for compose commands.

        Args:
            spec (EngineSpec): Engine compose metadata.
        """
        self.spec = spec

    def up(self) -> subprocess.CompletedProcess[str]:
        """Start the stack and wait until services are healthy.

        Returns:
            CompletedProcess[str]: Successful compose up result.

        Raises:
            subprocess.CalledProcessError: If compose up fails.
            subprocess.TimeoutExpired: If the command exceeds the wait window.
        """
        timeout = self.spec.wait_timeout_seconds + 60
        return self._run(
            compose_up_command(self.spec.compose_path, self.spec.wait_timeout_seconds),
            timeout=timeout,
        )

    def down(self) -> subprocess.CompletedProcess[str]:
        """Stop the stack and remove volumes.

        Returns:
            CompletedProcess[str]: Compose down result (check=False).
        """
        try:
            return self._run(
                compose_down_command(self.spec.compose_path),
                timeout=120,
                check=False,
            )
        except (subprocess.TimeoutExpired, OSError):
            return subprocess.CompletedProcess(
                args=compose_down_command(self.spec.compose_path),
                returncode=1,
                stdout="",
                stderr="compose down failed",
            )

    def logs(self) -> str:
        """Return recent compose logs for failure diagnosis.

        Returns:
            str: Combined stdout and stderr from `docker compose logs`.
        """
        try:
            completed = self._run(
                compose_command(self.spec.compose_path, "logs", "--no-color"),
                timeout=30,
                check=False,
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            return str(exc)
        return f"{completed.stdout}\n{completed.stderr}"

    def _run(
        self,
        command: list[str],
        timeout: float,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        """Run a compose command from the repository root.

        Args:
            command (list[str]): Argv to execute.
            timeout (float): Process timeout in seconds.
            check (bool): Raise if the command exits non-zero.

        Returns:
            CompletedProcess[str]: Captured command result.

        Raises:
            subprocess.CalledProcessError: If check is True and the command fails.
            subprocess.TimeoutExpired: If the command exceeds `timeout`.
        """
        return subprocess.run(
            command,
            cwd=REPO_ROOT,
            check=check,
            capture_output=True,
            text=True,
            timeout=timeout,
        )


@contextmanager
def started_stack(spec: EngineSpec) -> Iterator[ComposeStack]:
    """Start a compose stack and always attempt teardown.

    Args:
        spec (EngineSpec): Engine compose metadata.

    Yields:
        ComposeStack: Started stack.

    Raises:
        subprocess.CalledProcessError: If compose up fails.
        RuntimeError: If compose up fails after capturing logs.
    """
    stack = ComposeStack(spec)
    try:
        stack.up()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        logs = stack.logs()
        stack.down()
        raise RuntimeError(
            f"Failed to start {spec.compose_file}: {exc}\n{logs}"
        ) from exc
    try:
        yield stack
    finally:
        stack.down()

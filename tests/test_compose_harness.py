"""Unit tests for the functional-test compose harness."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tests.functional.harness import (
    ENGINE_SPECS,
    PLACEHOLDER_PASSWORD,
    ComposeStack,
    compose_down_command,
    compose_up_command,
    docker_available,
    opt_in_enabled,
    settings_for,
)


def test_compose_up_command_waits_for_health() -> None:
    """Compose up uses detached mode, wait, and the engine timeout."""
    compose_file = Path("/tmp/postgres.yml")
    command = compose_up_command(compose_file, 120)
    assert command == [
        "docker",
        "compose",
        "-f",
        str(compose_file),
        "up",
        "-d",
        "--wait",
        "--wait-timeout",
        "120",
    ]


def test_compose_down_command_removes_volumes() -> None:
    """Compose down deletes volumes so the next run starts empty."""
    compose_file = Path("/tmp/mysql.yml")
    assert compose_down_command(compose_file) == [
        "docker",
        "compose",
        "-f",
        str(compose_file),
        "down",
        "-v",
        "--remove-orphans",
    ]


def test_settings_for_each_engine_uses_placeholders(tmp_path: Path) -> None:
    """Live settings point at compose ports and placeholder credentials."""
    sqlite = settings_for("sqlite", tmp_path)
    assert sqlite.normalized_driver == "sqlite"
    assert sqlite.sqlite_path == tmp_path / "bookmarks.db"

    postgres = settings_for("postgres", tmp_path)
    assert postgres.postgres_host == "127.0.0.1"
    assert postgres.postgres_port == 55432
    assert postgres.postgres_password == PLACEHOLDER_PASSWORD

    mysql = settings_for("mysql", tmp_path)
    assert mysql.mysql_port == 53306
    assert mysql.mysql_password == PLACEHOLDER_PASSWORD

    oracle = settings_for("oracle", tmp_path)
    assert oracle.oracle_dsn == "127.0.0.1:51521/FREEPDB1"
    assert oracle.oracle_password == PLACEHOLDER_PASSWORD


def test_settings_for_unknown_engine_raises(tmp_path: Path) -> None:
    """Unknown engine names fail fast."""
    with pytest.raises(KeyError, match="Unknown functional test engine"):
        settings_for("redis", tmp_path)


def test_opt_in_enabled_reads_oracle_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    """Oracle compose tests stay off unless RUN_ORACLE_FUNCTIONAL is set."""
    spec = ENGINE_SPECS["oracle"]
    monkeypatch.delenv("RUN_ORACLE_FUNCTIONAL", raising=False)
    assert opt_in_enabled(spec) is False
    monkeypatch.setenv("RUN_ORACLE_FUNCTIONAL", "1")
    assert opt_in_enabled(spec) is True
    assert opt_in_enabled(ENGINE_SPECS["postgres"]) is True


def test_docker_available_false_when_cli_missing() -> None:
    """A missing docker binary is treated as unavailable."""
    with patch(
        "tests.functional.harness.subprocess.run", side_effect=FileNotFoundError
    ):
        assert docker_available() is False


def test_compose_stack_up_runs_expected_command() -> None:
    """ComposeStack.up invokes docker compose up --wait."""
    spec = ENGINE_SPECS["postgres"]
    completed = MagicMock()
    with patch(
        "tests.functional.harness.subprocess.run",
        return_value=completed,
    ) as run:
        stack = ComposeStack(spec)
        assert stack.up() is completed
    run.assert_called_once()
    command = run.call_args.args[0]
    assert command[:4] == ["docker", "compose", "-f", str(spec.compose_path)]
    assert "up" in command
    assert "--wait" in command

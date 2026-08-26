"""Unit tests for the per-platform database test runner."""

import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from tests.functional.harness import ENGINE_SPECS
from tests.functional.runner import (
    extra_pytest_args,
    format_summary,
    functional_pytest_command,
    main,
    parse_args,
)


def test_functional_pytest_command_targets_one_engine() -> None:
    """Each platform run is scoped to that engine's live test."""
    command = functional_pytest_command("postgres", extra=["-q"])
    assert command[:5] == [
        "uv",
        "run",
        "pytest",
        "--functional",
        "tests/functional/test_live_drivers.py",
    ]
    assert command[command.index("-k") + 1] == "postgres"
    assert command[-1] == "-q"


def test_functional_pytest_command_rejects_unknown_engine() -> None:
    """Unknown engine names fail fast."""
    with pytest.raises(KeyError, match="Unknown functional test engine"):
        functional_pytest_command("redis")


def test_parse_args_defaults_to_every_engine() -> None:
    """The runner tests sqlite, postgres, mysql, and oracle by default."""
    args = parse_args([])
    assert args.engines == list(ENGINE_SPECS)


def test_parse_args_accepts_engine_subset() -> None:
    """--engines limits the matrix to the requested platforms."""
    args = parse_args(["--engines", "sqlite", "mysql"])
    assert args.engines == ["sqlite", "mysql"]


def test_extra_pytest_args_strips_separator() -> None:
    """A leading -- is not forwarded to pytest."""
    assert extra_pytest_args(["--", "-q", "-s"]) == ["-q", "-s"]
    assert extra_pytest_args(["-q"]) == ["-q"]


def test_format_summary_reports_pass_and_fail() -> None:
    """The summary lists each engine and its pytest exit code."""
    text = format_summary([("sqlite", 0), ("mysql", 1)])
    assert "sqlite  PASS" in text
    assert "mysql   FAIL (1)" in text


def test_main_returns_2_when_docker_is_missing() -> None:
    """The runner fails fast when the Docker daemon is down."""
    with patch("tests.functional.runner.docker_available", return_value=False):
        assert main(["--engines", "sqlite"]) == 2


def test_main_runs_each_engine_and_returns_failure(monkeypatch) -> None:
    """A failed engine does not skip later platforms; overall status is 1."""
    calls: list[str] = []

    def _fake_run(engine: str, extra: list[str]) -> int:
        """Record the engine and fail mysql only.

        Args:
            engine (str): Canonical driver name.
            extra (list[str]): Extra pytest arguments.

        Returns:
            int: Fake pytest exit code.
        """
        _ = extra
        calls.append(engine)
        return 1 if engine == "mysql" else 0

    monkeypatch.setattr("tests.functional.runner.docker_available", lambda: True)
    monkeypatch.setattr("tests.functional.runner.run_engine", _fake_run)
    assert main(["--engines", "sqlite", "mysql", "oracle"]) == 1
    assert calls == ["sqlite", "mysql", "oracle"]


def test_script_help_exits_zero() -> None:
    """The repo script entry point prints help without starting Docker."""
    repo = Path(__file__).resolve().parents[1]
    completed = subprocess.run(
        [sys.executable, str(repo / "scripts" / "run_database_tests.py"), "--help"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0
    assert "sqlite" in completed.stdout
    assert "oracle" in completed.stdout

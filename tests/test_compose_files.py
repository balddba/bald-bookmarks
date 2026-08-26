"""Sanitization checks for example env and compose files."""

import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
COMPOSE_DIR = REPO_ROOT / "compose"
EXAMPLE_FILES = [
    REPO_ROOT / ".env.example",
    REPO_ROOT / "docker-compose.yml",
    REPO_ROOT / "docker-compose.demo.yaml",
    *sorted(COMPOSE_DIR.glob("*.yml")),
]
FORBIDDEN_SUBSTRINGS = (
    "lugnuts",
    "aaronslab",
)
REQUIRED_COMPOSE_ENGINES = ("sqlite", "postgres", "mysql", "oracle")


def test_example_files_do_not_contain_live_secrets() -> None:
    """Example and compose files use placeholders, not live host credentials."""
    missing = [path for path in EXAMPLE_FILES if not path.is_file()]
    assert missing == [], f"Missing example files: {missing}"
    for path in EXAMPLE_FILES:
        text = path.read_text(encoding="utf-8").lower()
        for needle in FORBIDDEN_SUBSTRINGS:
            assert needle not in text, f"{path.name} contains forbidden value {needle}"


def test_env_example_uses_placeholder_credentials() -> None:
    """`.env.example` documents placeholder passwords and a local Oracle DSN."""
    text = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    assert "ORACLE_PASSWORD=changeme" in text
    assert "POSTGRES_PASSWORD=changeme" in text
    assert "MYSQL_PASSWORD=changeme" in text
    assert "ORACLE_DSN=localhost:1521/FREEPDB1" in text
    assert "DB_DRIVER=sqlite" in text


def test_compose_files_exist_for_each_engine() -> None:
    """Each database engine has a compose file with a healthcheck."""
    for engine in REQUIRED_COMPOSE_ENGINES:
        path = COMPOSE_DIR / f"{engine}.yml"
        assert path.is_file(), f"Missing compose/{engine}.yml"
        text = path.read_text(encoding="utf-8")
        assert "healthcheck:" in text
        assert "changeme" in text or engine == "sqlite"


def test_compose_files_are_valid_when_docker_cli_exists() -> None:
    """`docker compose config` accepts each engine file when the CLI is installed."""
    docker = shutil.which("docker")
    if docker is None:
        pytest.skip("docker CLI is not installed")
    for engine in REQUIRED_COMPOSE_ENGINES:
        path = COMPOSE_DIR / f"{engine}.yml"
        completed = subprocess.run(
            [docker, "compose", "-f", str(path), "config"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        assert completed.returncode == 0, (
            f"compose/{engine}.yml is invalid:\n{completed.stderr or completed.stdout}"
        )


def test_demo_compose_file_is_valid_when_docker_cli_exists() -> None:
    """Validate `docker-compose.demo.yaml` using `docker compose config`."""
    docker = shutil.which("docker")
    if docker is None:
        pytest.skip("docker CLI is not installed")
    demo_file = REPO_ROOT / "docker-compose.demo.yaml"
    completed = subprocess.run(
        [docker, "compose", "-f", str(demo_file), "config"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    assert completed.returncode == 0, (
        f"docker-compose.demo.yaml is invalid:\n{completed.stderr or completed.stdout}"
    )

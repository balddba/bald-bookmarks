"""CLI to run live DatabaseDriver tests once per compose stack."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from collections.abc import Sequence

from tests.functional.harness import (
    ENGINE_SPECS,
    ORACLE_OPT_IN_ENV,
    REPO_ROOT,
    docker_available,
)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Parse command-line options for the platform matrix runner.

    Args:
        argv (Sequence[str] | None): Arguments excluding the program name.

    Returns:
        argparse.Namespace: Parsed engines and extra pytest arguments.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Run live DatabaseDriver tests once per database platform "
            "(sqlite, postgres, mysql, oracle)."
        )
    )
    parser.add_argument(
        "--engines",
        nargs="+",
        choices=list(ENGINE_SPECS),
        default=list(ENGINE_SPECS),
        help="Engines to test in order (default: all four platforms).",
    )
    parser.add_argument(
        "pytest_args",
        nargs=argparse.REMAINDER,
        help="Extra pytest arguments. Prefix with -- if they start with a dash.",
    )
    return parser.parse_args(argv)


def extra_pytest_args(raw: Sequence[str]) -> list[str]:
    """Strip a leading -- separator from remainder pytest arguments.

    Args:
        raw (Sequence[str]): Remainder arguments from argparse.

    Returns:
        list[str]: Arguments to append to pytest.
    """
    args = list(raw)
    if args and args[0] == "--":
        return args[1:]
    return args


def functional_pytest_command(
    engine: str,
    extra: Sequence[str] = (),
) -> list[str]:
    """Build the pytest command for one database platform.

    Args:
        engine (str): Canonical driver name (sqlite, postgres, mysql, oracle).
        extra (Sequence[str]): Extra pytest arguments.

    Returns:
        list[str]: Command argv.

    Raises:
        KeyError: If `engine` is not a known functional-test engine.
    """
    if engine not in ENGINE_SPECS:
        raise KeyError(f"Unknown functional test engine: {engine}")
    command = [
        "uv",
        "run",
        "pytest",
        "--functional",
        "tests/functional/test_live_drivers.py",
        "-k",
        engine,
        "-vv",
    ]
    command.extend(extra)
    return command


def run_engine(engine: str, extra: Sequence[str] = ()) -> int:
    """Run live tests for one engine, enabling Oracle opt-in.

    Args:
        engine (str): Canonical driver name.
        extra (Sequence[str]): Extra pytest arguments.

    Returns:
        int: Pytest process exit code.
    """
    env = os.environ.copy()
    env[ORACLE_OPT_IN_ENV] = "1"
    completed = subprocess.run(
        functional_pytest_command(engine, extra),
        cwd=REPO_ROOT,
        env=env,
        check=False,
    )
    return completed.returncode


def format_summary(results: Sequence[tuple[str, int]]) -> str:
    """Format per-engine pass/fail lines.

    Args:
        results (Sequence[tuple[str, int]]): Engine name and pytest exit code.

    Returns:
        str: Human-readable summary block.
    """
    width = max((len(name) for name, _ in results), default=0)
    lines = ["=== database platform summary ==="]
    for name, code in results:
        status = "PASS" if code == 0 else f"FAIL ({code})"
        lines.append(f"{name.ljust(width)}  {status}")
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    """Run live tests for each selected database platform.

    Args:
        argv (Sequence[str] | None): Arguments excluding the program name.

    Returns:
        int: 0 when every engine passes, 1 when any engine fails, 2 when Docker
            is unavailable.
    """
    args = parse_args(argv)
    extra = extra_pytest_args(args.pytest_args)
    if not docker_available():
        print("Docker daemon is not available.", file=sys.stderr)
        return 2

    results: list[tuple[str, int]] = []
    overall = 0
    for engine in args.engines:
        print(f"\n=== {engine} ===\n", flush=True)
        code = run_engine(engine, extra)
        results.append((engine, code))
        if code != 0:
            overall = 1

    print()
    print(format_summary(results), flush=True)
    return overall


if __name__ == "__main__":
    raise SystemExit(main())

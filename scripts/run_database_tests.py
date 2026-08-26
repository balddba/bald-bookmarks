#!/usr/bin/env python3
"""Run live DatabaseDriver tests once per database platform.

Starts each compose stack under compose/ and runs the functional driver plus
API workflow against sqlite, postgres, mysql, and oracle.
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    """Put the repo on sys.path and run the platform matrix.

    Returns:
        int: Process exit code from the platform matrix.
    """
    sys.path.insert(0, str(REPO_ROOT))
    sys.path.insert(0, str(REPO_ROOT / "backend"))
    # Import after path setup so tests.functional is resolvable.
    from tests.functional.runner import main as run_matrix

    return run_matrix()


if __name__ == "__main__":
    raise SystemExit(main())

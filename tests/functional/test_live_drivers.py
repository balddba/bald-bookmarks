"""Live tests that start per-engine docker compose stacks."""

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from bald_bookmarks.db.factory import create_driver
from bald_bookmarks.db.migrate import upgrade_schema
from bald_bookmarks.main import create_app
from tests.functional.harness import (
    ENGINE_SPECS,
    docker_available,
    opt_in_enabled,
    settings_for,
    started_stack,
)
from tests.functional.workflow import (
    assert_api_workflow,
    assert_driver_workflow,
    write_tiny_png,
)


@pytest.mark.functional
@pytest.mark.parametrize("engine", list(ENGINE_SPECS))
def test_compose_database_workflow(engine: str, tmp_path: Path) -> None:
    """Start the engine compose stack and run driver plus API workflows.

    Args:
        engine (str): Canonical driver name from ENGINE_SPECS.
        tmp_path (Path): Pytest temporary directory.
    """
    spec = ENGINE_SPECS[engine]
    if not docker_available():
        pytest.skip("Docker daemon is not available")
    if not opt_in_enabled(spec):
        pytest.skip(f"Set {spec.opt_in_env}=1 to run {engine} compose tests")

    settings = settings_for(engine, tmp_path)
    with started_stack(spec):
        upgrade_schema(settings)
        driver = create_driver(settings)
        driver.connect()
        try:
            assert_driver_workflow(driver)
        finally:
            driver.close()

        app = create_app(settings)
        with (
            patch(
                "bald_bookmarks.jobs.handlers.thumbnail.capture_page_preview",
                side_effect=write_tiny_png,
            ),
            TestClient(app) as client,
        ):
            assert_api_workflow(client)

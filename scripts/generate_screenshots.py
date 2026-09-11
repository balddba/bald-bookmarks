"""Script to generate documentation screenshots from running demo application.

Launches Playwright Chromium, navigates to demo application routes,
and captures high-resolution screenshots for documentation.
"""

from pathlib import Path

from loguru import logger
from playwright.sync_api import sync_playwright

BASE_URL = "http://localhost:8080"
OUTPUT_DIR = Path(__file__).parent.parent / "docs" / "screenshots"


def capture_screenshots() -> None:
    """Capture documentation screenshots from demo app."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        # Use desktop viewport with 2x scale for crisp documentation images
        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            device_scale_factor=2,
        )
        page = context.new_page()

        # 1. Main Dashboard
        logger.info("Capturing Main Dashboard...")
        page.goto(f"{BASE_URL}/", wait_until="networkidle")
        page.wait_for_selector(".app-container, .main-layout, body")
        # Expand all folder nodes if possible
        toggle_selector = (
            ".folder-tree-toggle, button:has-text('▶'), button:has-text('▼')"
        )
        folder_tree_toggle = page.query_selector_all(toggle_selector)
        for toggle in folder_tree_toggle:
            try:
                toggle.click()
            except Exception:
                pass
        page.wait_for_timeout(1000)
        main_path = OUTPUT_DIR / "main-dashboard.png"
        page.screenshot(path=str(main_path))
        logger.info(f"Saved {main_path}")

        # 2. Folder View (e.g. Python & FastAPI folder)
        logger.info("Capturing Folder View...")
        folder_item = page.get_by_text("Python & FastAPI", exact=False).first
        if folder_item.is_visible():
            folder_item.click()
            page.wait_for_timeout(1000)
        folder_path = OUTPUT_DIR / "folder-view.png"
        page.screenshot(path=str(folder_path))
        logger.info(f"Saved {folder_path}")

        # 3. Admin Configuration
        logger.info("Capturing Admin Configuration...")
        page.goto(f"{BASE_URL}/admin/configuration", wait_until="networkidle")
        page.wait_for_timeout(1000)
        admin_config_path = OUTPUT_DIR / "admin-configuration.png"
        page.screenshot(path=str(admin_config_path))
        logger.info(f"Saved {admin_config_path}")

        # 4. Admin Jobs
        logger.info("Capturing Admin Jobs...")
        page.goto(f"{BASE_URL}/admin/jobs", wait_until="networkidle")
        page.wait_for_timeout(1000)
        admin_jobs_path = OUTPUT_DIR / "admin-jobs.png"
        page.screenshot(path=str(admin_jobs_path))
        logger.info(f"Saved {admin_jobs_path}")

        # 5. Admin Database
        logger.info("Capturing Admin Database...")
        page.goto(f"{BASE_URL}/admin/database", wait_until="networkidle")
        page.wait_for_timeout(1000)
        admin_db_path = OUTPUT_DIR / "admin-database.png"
        page.screenshot(path=str(admin_db_path))
        logger.info(f"Saved {admin_db_path}")

        browser.close()
        logger.info("Finished capturing screenshots.")


if __name__ == "__main__":
    capture_screenshots()

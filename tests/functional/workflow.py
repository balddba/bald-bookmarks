"""Shared functional assertions against a live DatabaseDriver and API."""

from pathlib import Path

from fastapi.testclient import TestClient

from bald_bookmarks.db.abc import DatabaseDriver
from bald_bookmarks.domain.bookmarks import BookmarkCreate
from bald_bookmarks.domain.folders import FolderCreate
from bald_bookmarks.domain.jobs import JobEnqueue, ThumbnailCapturePayload

_TINY_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


def write_tiny_png(url: str, destination: Path, **_: object) -> Path:
    """Write a 1x1 PNG so live tests do not launch Chromium.

    Args:
        url (str): Bookmark URL (unused).
        destination (Path): Output path.
        **_ (object): Ignored capture options.

    Returns:
        Path: Written destination path.
    """
    _ = url
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(_TINY_PNG)
    return destination


def assert_driver_workflow(driver: DatabaseDriver) -> None:
    """Exercise folder, bookmark, tag, and job claim on a live driver.

    Args:
        driver (DatabaseDriver): Connected driver with schema applied.
    """
    health = driver.health_check()
    assert health.ok is True
    assert driver.alembic_revision()

    root = driver.create_folder(FolderCreate(name="Work"))
    child = driver.create_folder(FolderCreate(name="Docs", parent_id=root.id))
    tree = driver.get_folder_tree()
    assert tree[0].name == "Work"
    assert tree[0].children[0].id == child.id

    bookmark = driver.create_bookmark(
        BookmarkCreate(
            title="Example",
            url="https://example.com",
            folder_id=child.id,
            tag_names=["news", "daily"],
        )
    )
    assert {tag.name for tag in bookmark.tags} == {"news", "daily"}

    job = driver.enqueue_job(
        JobEnqueue(
            job_type="thumbnail.capture",
            payload_json=ThumbnailCapturePayload(
                bookmark_id=bookmark.id
            ).model_dump_json(),
        )
    )
    claimed = driver.claim_next_job()
    assert claimed is not None
    assert claimed.id == job.id
    driver.mark_job_succeeded(claimed.id)
    assert driver.get_job(claimed.id).status.value == "succeeded"

    listed = driver.list_bookmarks(folder_id=child.id)
    assert len(listed) == 1
    assert listed[0].title == "Example"

    driver.delete_folder(root.id, recursive=True)
    assert driver.get_folder_tree() == []
    assert driver.list_bookmarks() == []


def assert_api_workflow(client: TestClient) -> None:
    """Exercise the HTTP API against a live database.

    Args:
        client (TestClient): FastAPI test client with lifespan started.
    """
    health = client.get("/api/health")
    assert health.status_code == 200
    assert health.json() == {"status": "ok"}

    root = client.post("/api/folders", json={"name": "Work"}).json()
    child = client.post(
        "/api/folders",
        json={"name": "Docs", "parent_id": root["id"]},
    ).json()
    tree = client.get("/api/folders/tree").json()
    assert tree[0]["name"] == "Work"
    assert tree[0]["children"][0]["id"] == child["id"]

    created = client.post(
        "/api/bookmarks",
        json={
            "title": "Alpha Site",
            "url": "https://alpha.test",
            "folder_id": child["id"],
            "tag_names": ["alpha"],
        },
    )
    assert created.status_code == 201
    bookmark = created.json()
    assert bookmark["thumbnail_status"] == "pending"
    assert [tag["name"] for tag in bookmark["tags"]] == ["alpha"]

    jobs = client.get("/api/jobs").json()
    assert any(job["job_type"] == "thumbnail.capture" for job in jobs)

    search = client.get("/api/bookmarks?q=alpha").json()
    assert len(search) == 1
    assert search[0]["title"] == "Alpha Site"

    deleted = client.delete(f"/api/folders/{root['id']}?recursive=true")
    assert deleted.status_code == 204
    assert client.get("/api/folders/tree").json() == []
    assert client.get("/api/bookmarks").json() == []

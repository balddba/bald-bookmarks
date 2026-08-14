"""API tests using the in-memory DatabaseDriver."""

from fastapi.testclient import TestClient


def test_health(client: TestClient) -> None:
    """Health endpoint returns ok."""
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_folder_tree_and_nested_create(client: TestClient) -> None:
    """Folders nest and appear in the tree endpoint."""
    root = client.post("/api/folders", json={"name": "Work"}).json()
    child = client.post(
        "/api/folders",
        json={"name": "Docs", "parent_id": root["id"]},
    ).json()
    tree = client.get("/api/folders/tree").json()
    assert tree[0]["name"] == "Work"
    assert tree[0]["children"][0]["id"] == child["id"]
    children = client.get(f"/api/folders/{root['id']}/children").json()
    assert len(children) == 1
    assert children[0]["name"] == "Docs"


def test_folder_tree_includes_bookmark_counts(client: TestClient) -> None:
    """Folder tree reports direct bookmark counts per folder."""
    root = client.post("/api/folders", json={"name": "Work"}).json()
    child = client.post(
        "/api/folders",
        json={"name": "Docs", "parent_id": root["id"]},
    ).json()
    client.post(
        "/api/bookmarks",
        json={
            "title": "Root page",
            "url": "https://example.com/root",
            "folder_id": root["id"],
        },
    )
    client.post(
        "/api/bookmarks",
        json={
            "title": "Child page",
            "url": "https://example.com/child",
            "folder_id": child["id"],
        },
    )
    tree = client.get("/api/folders/tree").json()
    assert tree[0]["bookmark_count"] == 1
    assert tree[0]["children"][0]["bookmark_count"] == 1


def test_folder_move_cycle_rejected(client: TestClient) -> None:
    """Moving a folder under its descendant is rejected."""
    root = client.post("/api/folders", json={"name": "A"}).json()
    child = client.post(
        "/api/folders",
        json={"name": "B", "parent_id": root["id"]},
    ).json()
    response = client.patch(
        f"/api/folders/{root['id']}",
        json={"parent_id": child["id"]},
    )
    assert response.status_code == 400


def test_folder_delete_requires_recursive(client: TestClient) -> None:
    """Non-empty folder delete conflicts without recursive=true."""
    root = client.post("/api/folders", json={"name": "Keep"}).json()
    client.post("/api/folders", json={"name": "Child", "parent_id": root["id"]})
    conflict = client.delete(f"/api/folders/{root['id']}")
    assert conflict.status_code == 409
    deleted = client.delete(f"/api/folders/{root['id']}?recursive=true")
    assert deleted.status_code == 204


def test_folder_recursive_delete_removes_nested_bookmarks(
    client: TestClient,
) -> None:
    """Recursive folder delete removes nested folders and their bookmarks."""
    root = client.post("/api/folders", json={"name": "Work"}).json()
    child = client.post(
        "/api/folders",
        json={"name": "Docs", "parent_id": root["id"]},
    ).json()
    client.post(
        "/api/bookmarks",
        json={
            "title": "Root page",
            "url": "https://example.com/root",
            "folder_id": root["id"],
        },
    )
    client.post(
        "/api/bookmarks",
        json={
            "title": "Child page",
            "url": "https://example.com/child",
            "folder_id": child["id"],
        },
    )
    deleted = client.delete(f"/api/folders/{root['id']}?recursive=true")
    assert deleted.status_code == 204
    assert client.get("/api/folders/tree").json() == []
    assert client.get("/api/bookmarks").json() == []
    missing = client.get(f"/api/folders/{root['id']}")
    assert missing.status_code == 404


def test_bookmark_crud_tags_and_thumbnail_job(client: TestClient) -> None:
    """Bookmarks support tags and enqueue thumbnail jobs."""
    folder = client.post("/api/folders", json={"name": "Reading"}).json()
    created = client.post(
        "/api/bookmarks",
        json={
            "title": "Example",
            "url": "https://example.com",
            "folder_id": folder["id"],
            "tag_names": ["News", "daily"],
        },
    )
    assert created.status_code == 201
    bookmark = created.json()
    assert bookmark["thumbnail_status"] == "pending"
    assert {tag["name"] for tag in bookmark["tags"]} == {"news", "daily"}

    jobs = client.get("/api/jobs").json()
    assert jobs
    assert jobs[0]["job_type"] == "thumbnail.capture"

    listed = client.get(f"/api/bookmarks?folder_id={folder['id']}").json()
    assert len(listed) == 1

    updated = client.patch(
        f"/api/bookmarks/{bookmark['id']}",
        json={"title": "Example Updated", "tag_names": ["news"]},
    ).json()
    assert updated["title"] == "Example Updated"
    assert [tag["name"] for tag in updated["tags"]] == ["news"]

    refreshed = client.post(f"/api/bookmarks/{bookmark['id']}/thumbnail/refresh")
    assert refreshed.status_code == 200
    assert refreshed.json()["thumbnail_status"] == "pending"

    deleted = client.delete(f"/api/bookmarks/{bookmark['id']}")
    assert deleted.status_code == 204


def test_bookmark_description_rejects_over_max_length(client: TestClient) -> None:
    """Bookmark descriptions longer than VARCHAR2(256) are rejected."""
    too_long = "x" * 257
    created = client.post(
        "/api/bookmarks",
        json={
            "title": "Long desc",
            "url": "https://example.com/long",
            "description": too_long,
        },
    )
    assert created.status_code == 422
    ok = client.post(
        "/api/bookmarks",
        json={
            "title": "Fit desc",
            "url": "https://example.com/fit",
            "description": "x" * 256,
        },
    )
    assert ok.status_code == 201
    assert ok.json()["description"] == "x" * 256


def test_tag_create_conflict_and_list(client: TestClient) -> None:
    """Duplicate tags conflict and listing returns created tags."""
    first = client.post("/api/tags", json={"name": "Rust"})
    assert first.status_code == 201
    conflict = client.post("/api/tags", json={"name": " rust "})
    assert conflict.status_code == 409
    tags = client.get("/api/tags").json()
    assert any(tag["name"] == "rust" for tag in tags)


def test_bookmark_search_and_tag_filter(client: TestClient) -> None:
    """Search and tag filters narrow bookmark lists."""
    client.post(
        "/api/bookmarks",
        json={
            "title": "Alpha Site",
            "url": "https://alpha.test",
            "tag_names": ["alpha"],
        },
    )
    client.post(
        "/api/bookmarks",
        json={
            "title": "Beta Site",
            "url": "https://beta.test",
            "tag_names": ["beta"],
        },
    )
    search = client.get("/api/bookmarks?q=alpha").json()
    assert len(search) == 1
    assert search[0]["title"] == "Alpha Site"
    tagged = client.get("/api/bookmarks?tag=beta").json()
    assert len(tagged) == 1
    assert tagged[0]["title"] == "Beta Site"

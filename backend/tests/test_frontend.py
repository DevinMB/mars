"""Exercise public file serving through HTTP, including URL decoding."""
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.frontend import mount_frontend


@pytest.fixture
def client(tmp_path):
    root = tmp_path / "static"
    (root / "assets").mkdir(parents=True)
    (root / "index.html").write_text("<html>MARS</html>")
    (root / "mark.svg").write_text("public icon")
    (root / "assets/app.js").write_text("public script")
    private = tmp_path / "private.txt"
    private.write_text("outside sentinel")
    (root / "link.txt").symlink_to(private)
    sibling = tmp_path / "static-private"
    sibling.mkdir()
    (sibling / "private.txt").write_text("sibling sentinel")
    app = FastAPI()
    mount_frontend(app, root)
    return TestClient(app)


@pytest.mark.parametrize("path", [
    "/%2e%2e/private.txt", "/..%2fprivate.txt",
    "/%2e%2e/static-private/private.txt", "/link.txt",
    "/assets/%2e%2e/%2e%2e/private.txt", "/%2Fetc/passwd",
])
def test_outside_files_are_never_public(client, path):
    assert client.get(path).status_code == 404


@pytest.mark.parametrize("path,body", [
    ("/", "<html>MARS</html>"), ("/jobs/example/edit", "<html>MARS</html>"),
    ("/mark.svg", "public icon"), ("/assets/app.js", "public script"),
])
def test_public_files_and_deep_links(client, path, body):
    response = client.get(path)
    assert response.status_code == 200
    assert response.text == body


def test_unknown_api_stays_404(client):
    assert client.get("/api/missing").status_code == 404

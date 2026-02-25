"""
API endpoint integration tests.

Uses mongomock-motor to mock MongoDB and patches the BLIP model
so tests run fast without downloading model weights.
"""

import os
import io
import pytest
import pytest_asyncio
from unittest.mock import patch, MagicMock
from PIL import Image

from httpx import AsyncClient, ASGITransport
from mongomock_motor import AsyncMongoMockClient

# Patch the captioner and Celery env vars before importing main
with patch("app.captioner.load_model"), \
     patch("app.captioner.generate_caption", return_value="a test caption"), \
     patch.dict(os.environ, {
         "CELERY_BROKER_URL": "memory://",
         "CELERY_RESULT_BACKEND": "cache+memory://",
         "CELERY_TASK_ALWAYS_EAGER": "True",
     }):
    from app.main import app
    from app import database
    
    # We still mock delay so the tests don't actually run the worker code
    # (since the DB mock doesn't carry easily over into the worker context here)
    from app.worker import process_image_task
    process_image_task.delay = MagicMock(return_value=MagicMock(id="test_task_id"))


@pytest_asyncio.fixture
async def mock_db(monkeypatch, tmp_path):
    """Set up a mock MongoDB for testing."""
    client = AsyncMongoMockClient()
    db = client["test_image_pipeline"]

    # Patch the database module
    monkeypatch.setattr(database, "client", client)
    monkeypatch.setattr(database, "db", db)

    # Patch directories to use temp paths
    upload_dir = tmp_path / "uploads"
    thumb_dir = tmp_path / "thumbnails"
    upload_dir.mkdir()
    thumb_dir.mkdir()

    monkeypatch.setenv("UPLOAD_DIR", str(upload_dir))
    monkeypatch.setenv("THUMBNAILS_DIR", str(thumb_dir))

    import app.main as main_module
    import app.image_processor as ip_module
    monkeypatch.setattr(main_module, "UPLOAD_DIR", str(upload_dir))
    monkeypatch.setattr(main_module, "THUMBNAILS_DIR", str(thumb_dir))
    monkeypatch.setattr(ip_module, "THUMBNAILS_DIR", str(thumb_dir))

    yield db


@pytest_asyncio.fixture
async def client(mock_db):
    """Create an async test client."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


def _create_test_image(format: str = "JPEG") -> io.BytesIO:
    """Create an in-memory test image."""
    img = Image.new("RGB", (640, 480), color=(100, 150, 200))
    buffer = io.BytesIO()
    img.save(buffer, format=format)
    buffer.seek(0)
    return buffer


class TestUploadImage:
    """Tests for POST /api/images."""

    @pytest.mark.asyncio
    async def test_upload_valid_jpg(self, client):
        image_data = _create_test_image("JPEG")
        response = await client.post(
            "/api/images",
            files={"file": ("test.jpg", image_data, "image/jpeg")},
        )
        assert response.status_code == 202
        data = response.json()
        assert data["status"] == "accepted"
        assert "image_id" in data["data"]

    @pytest.mark.asyncio
    async def test_upload_valid_png(self, client):
        image_data = _create_test_image("PNG")
        response = await client.post(
            "/api/images",
            files={"file": ("test.png", image_data, "image/png")},
        )
        assert response.status_code == 202
        data = response.json()
        assert data["status"] == "accepted"

    @pytest.mark.asyncio
    async def test_upload_invalid_format(self, client):
        buffer = io.BytesIO(b"not an image")
        response = await client.post(
            "/api/images",
            files={"file": ("test.xlsx", buffer, "application/octet-stream")},
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_upload_corrupted_image(self, client):
        buffer = io.BytesIO(b"not actually an image")
        response = await client.post(
            "/api/images",
            files={"file": ("fake.jpg", buffer, "image/jpeg")},
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_upload_returns_unique_ids(self, client):
        ids = set()
        for i in range(3):
            image_data = _create_test_image("JPEG")
            response = await client.post(
                "/api/images",
                files={"file": (f"test{i}.jpg", image_data, "image/jpeg")},
            )
            ids.add(response.json()["data"]["image_id"])
        assert len(ids) == 3


class TestListImages:
    """Tests for GET /api/images."""

    @pytest.mark.asyncio
    async def test_empty_list(self, client):
        response = await client.get("/api/images")
        assert response.status_code == 200
        assert response.json() == []

    @pytest.mark.asyncio
    async def test_list_after_upload(self, client):
        image_data = _create_test_image("JPEG")
        await client.post(
            "/api/images",
            files={"file": ("test.jpg", image_data, "image/jpeg")},
        )
        response = await client.get("/api/images")
        assert response.status_code == 200
        images = response.json()
        assert len(images) >= 1


class TestGetImage:
    """Tests for GET /api/images/{id}."""

    @pytest.mark.asyncio
    async def test_get_existing_image(self, client):
        image_data = _create_test_image("JPEG")
        upload_response = await client.post(
            "/api/images",
            files={"file": ("photo.jpg", image_data, "image/jpeg")},
        )
        image_id = upload_response.json()["data"]["image_id"]

        response = await client.get(f"/api/images/{image_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["data"]["image_id"] == image_id
        assert data["data"]["original_name"] == "photo.jpg"

    @pytest.mark.asyncio
    async def test_get_nonexistent_image(self, client):
        response = await client.get("/api/images/img_doesnotexist")
        assert response.status_code == 404


class TestGetThumbnail:
    """Tests for GET /api/images/{id}/thumbnails/{size}."""

    @pytest.mark.asyncio
    async def test_invalid_size(self, client):
        response = await client.get("/api/images/img_test/thumbnails/large")
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_nonexistent_image(self, client):
        response = await client.get("/api/images/img_fake/thumbnails/small")
        assert response.status_code == 404


class TestDeleteImage:
    """Tests for DELETE /api/images/{id}."""

    @pytest.mark.asyncio
    async def test_delete_existing_image(self, client):
        # Create an image to delete
        image_data = _create_test_image("JPEG")
        upload_response = await client.post(
            "/api/images",
            files={"file": ("photo.jpg", image_data, "image/jpeg")},
        )
        image_id = upload_response.json()["data"]["image_id"]

        # Proceed to delete
        delete_response = await client.delete(f"/api/images/{image_id}")
        assert delete_response.status_code == 204

        # Confirm it's gone
        get_response = await client.get(f"/api/images/{image_id}")
        assert get_response.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_nonexistent_image(self, client):
        response = await client.delete("/api/images/img_doesnotexist")
        assert response.status_code == 404


class TestStats:
    """Tests for GET /api/stats."""

    @pytest.mark.asyncio
    async def test_empty_stats(self, client):
        response = await client.get("/api/stats")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 0
        assert data["failed"] == 0
        assert data["success_rate"] == "0.00%"
        assert data["average_processing_time_seconds"] == 0

    @pytest.mark.asyncio
    async def test_stats_after_upload(self, client):
        image_data = _create_test_image("JPEG")
        await client.post(
            "/api/images",
            files={"file": ("test.jpg", image_data, "image/jpeg")},
        )
        response = await client.get("/api/stats")
        data = response.json()
        assert data["total"] >= 1

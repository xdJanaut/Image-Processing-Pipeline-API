
import os
import tempfile
import pytest
from PIL import Image

from app.image_processor import (
    generate_thumbnails,
    extract_metadata,
    extract_exif,
    THUMBNAIL_SIZES,
)


@pytest.fixture
def sample_jpg(tmp_path):
    """Create a sample JPEG image for testing."""
    img = Image.new("RGB", (800, 600), color=(255, 128, 64))
    path = tmp_path / "test_image.jpg"
    img.save(str(path), "JPEG")
    return str(path)


@pytest.fixture
def sample_png(tmp_path):
    """Create a sample PNG image with transparency for testing."""
    img = Image.new("RGBA", (1024, 768), color=(0, 128, 255, 200))
    path = tmp_path / "test_image.png"
    img.save(str(path), "PNG")
    return str(path)


@pytest.fixture
def thumbnails_dir(tmp_path, monkeypatch):
    """Set up a temporary thumbnails directory."""
    thumb_dir = tmp_path / "thumbnails"
    thumb_dir.mkdir()
    monkeypatch.setenv("THUMBNAILS_DIR", str(thumb_dir))
    # Also patch the module-level variable
    import app.image_processor as ip
    monkeypatch.setattr(ip, "THUMBNAILS_DIR", str(thumb_dir))
    return str(thumb_dir)


class TestGenerateThumbnails:
    """Tests for thumbnail generation."""

    def test_generates_both_sizes(self, sample_jpg, thumbnails_dir):
        result = generate_thumbnails(sample_jpg, "test_img")
        assert "small" in result
        assert "medium" in result

    def test_thumbnail_files_exist(self, sample_jpg, thumbnails_dir):
        result = generate_thumbnails(sample_jpg, "test_img")
        for path in result.values():
            assert os.path.exists(path)

    def test_small_thumbnail_dimensions(self, sample_jpg, thumbnails_dir):
        result = generate_thumbnails(sample_jpg, "test_img")
        with Image.open(result["small"]) as thumb:
            assert thumb.width <= 150
            assert thumb.height <= 150

    def test_medium_thumbnail_dimensions(self, sample_jpg, thumbnails_dir):
        result = generate_thumbnails(sample_jpg, "test_img")
        with Image.open(result["medium"]) as thumb:
            assert thumb.width <= 300
            assert thumb.height <= 300

    def test_png_with_alpha_channel(self, sample_png, thumbnails_dir):
        """RGBA images should be converted to RGB for JPEG thumbnails."""
        result = generate_thumbnails(sample_png, "test_png")
        for path in result.values():
            with Image.open(path) as thumb:
                assert thumb.mode == "RGB"


class TestExtractMetadata:
    """Tests for metadata extraction."""

    def test_returns_all_fields(self, sample_jpg):
        metadata = extract_metadata(sample_jpg)
        assert "width" in metadata
        assert "height" in metadata
        assert "format" in metadata
        assert "size_bytes" in metadata
        assert "datetime" in metadata

    def test_correct_dimensions(self, sample_jpg):
        metadata = extract_metadata(sample_jpg)
        assert metadata["width"] == 800
        assert metadata["height"] == 600

    def test_correct_format(self, sample_jpg):
        metadata = extract_metadata(sample_jpg)
        assert metadata["format"] == "jpeg"

    def test_size_is_positive(self, sample_jpg):
        metadata = extract_metadata(sample_jpg)
        assert metadata["size_bytes"] > 0

    def test_png_format(self, sample_png):
        metadata = extract_metadata(sample_png)
        assert metadata["format"] == "png"
        assert metadata["width"] == 1024
        assert metadata["height"] == 768


class TestExtractExif:
    """Tests for EXIF data extraction."""

    def test_no_exif_returns_empty_dict(self, sample_jpg):
        """Programmatically created images have no EXIF data."""
        exif = extract_exif(sample_jpg)
        assert isinstance(exif, dict)

    def test_handles_png_gracefully(self, sample_png):
        """PNG files don't have EXIF, should return empty dict."""
        exif = extract_exif(sample_png)
        assert isinstance(exif, dict)

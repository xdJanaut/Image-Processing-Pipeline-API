"""
Image processing utilities: thumbnail generation, metadata extraction, EXIF parsing.
"""

import os
import logging
from datetime import datetime
from PIL import Image
from PIL.ExifTags import TAGS, GPSTAGS

logger = logging.getLogger(__name__)

THUMBNAIL_SIZES = {
    "small": (150, 150),
    "medium": (300, 300),
}

THUMBNAILS_DIR = os.getenv("THUMBNAILS_DIR", "thumbnails")


def generate_thumbnails(image_path: str, image_id: str) -> dict[str, str]:
    """Generate small and medium thumbnails for an image."""
    thumbnail_paths = {}

    with Image.open(image_path) as img:
        # Convert RGBA -> RGB for JPEG
        if img.mode in ("RGBA", "P"):
            img = img.convert("RGB")

        for size_name, dimensions in THUMBNAIL_SIZES.items():
            thumb = img.copy()
            thumb.thumbnail(dimensions, Image.LANCZOS)

            thumb_filename = f"{image_id}_{size_name}.jpg"
            thumb_path = os.path.join(THUMBNAILS_DIR, thumb_filename)
            thumb.save(thumb_path, "JPEG", quality=85)

            thumbnail_paths[size_name] = thumb_path
            logger.info(
                "Generated %s thumbnail (%dx%d) for %s",
                size_name, thumb.width, thumb.height, image_id,
            )

    return thumbnail_paths


def extract_metadata(image_path: str) -> dict:
    """Extract basic metadata from an image file."""
    file_stat = os.stat(image_path)

    with Image.open(image_path) as img:
        metadata = {
            "width": img.width,
            "height": img.height,
            "format": img.format.lower() if img.format else None,
            "size_bytes": file_stat.st_size,
            "datetime": datetime.fromtimestamp(
                file_stat.st_mtime
            ).isoformat(),
        }

    logger.info("Extracted metadata for %s: %dx%d %s",
                image_path, metadata["width"], metadata["height"],
                metadata["format"])
    return metadata


def extract_exif(image_path: str) -> dict:
    """
    Extract EXIF data from an image (primarily JPEG).
    Returns a dict of readable EXIF tags and values.
    """
    exif_data = {}

    try:
        with Image.open(image_path) as img:
            raw_exif = img.getexif()
            if not raw_exif:
                logger.info("No EXIF data found for %s", image_path)
                return exif_data

            for tag_id, value in raw_exif.items():
                tag_name = TAGS.get(tag_id, str(tag_id))

                # Convert bytes to string for JSON serialization
                if isinstance(value, bytes):
                    try:
                        value = value.decode("utf-8", errors="replace")
                    except Exception:
                        value = str(value)
                elif hasattr(value, "numerator"):
                    # Handle IFDRational type
                    value = float(value)

                exif_data[tag_name] = value

            # Try to extract GPS info if available
            gps_info = raw_exif.get_ifd(0x8825)
            if gps_info:
                gps_data = {}
                for tag_id, value in gps_info.items():
                    tag_name = GPSTAGS.get(tag_id, str(tag_id))
                    if isinstance(value, bytes):
                        value = value.decode("utf-8", errors="replace")
                    gps_data[tag_name] = str(value)
                exif_data["GPSInfo"] = gps_data

    except Exception as e:
        logger.warning("Failed to extract EXIF data from %s: %s",
                       image_path, str(e))

    logger.info("Extracted %d EXIF tags from %s",
                len(exif_data), image_path)
    return exif_data

"""
Pydantic response schemas matching the assessment specification format.
"""

from pydantic import BaseModel, Field, ConfigDict, field_serializer
from typing import Optional
from datetime import datetime


class ImageMetadata(BaseModel):
    """Image metadata fields."""
    model_config = ConfigDict(exclude_none=True)
    width: Optional[int] = None
    height: Optional[int] = None
    format: Optional[str] = None
    size_bytes: Optional[int] = None
    datetime: Optional[str] = None
    exif: Optional[dict] = None
    caption: Optional[str] = None


class ThumbnailUrls(BaseModel):
    """URLs for image thumbnails."""
    model_config = ConfigDict(exclude_none=True)
    small: Optional[str] = None
    medium: Optional[str] = None


class ImageData(BaseModel):
    """Core image data structure."""
    image_id: str
    original_name: str
    processed_at: Optional[str] = None
    metadata: ImageMetadata = Field(default_factory=ImageMetadata)
    thumbnails: ThumbnailUrls = Field(default_factory=ThumbnailUrls)

    @field_serializer("metadata", "thumbnails")
    def serialize_clean(self, v, _info):
        """Serialize sub-models excluding None values to return empty dicts."""
        return v.model_dump(exclude_none=True)


class ImageResponse(BaseModel):
    """Single image response matching the spec format."""
    status: str
    data: ImageData
    error: Optional[str] = None


class StatsResponse(BaseModel):
    """Processing statistics response."""
    total: int
    failed: int
    success_rate: str
    average_processing_time_seconds: float


class UploadResponse(BaseModel):
    """Response for image upload (async processing)."""
    status: str
    message: str
    data: dict

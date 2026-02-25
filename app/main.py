
import os
import uuid
import shutil
import logging
from datetime import datetime, timezone
from contextlib import asynccontextmanager

from PIL import Image
from fastapi import FastAPI, UploadFile, File, HTTPException, Query
from fastapi.responses import FileResponse

from app.database import connect_to_mongo, close_mongo_connection, get_database
from app.captioner import load_model
from app.worker import process_image_task
from app.schemas import (
    ImageResponse,
    ImageData,
    ImageMetadata,
    ThumbnailUrls,
    StatsResponse,
    UploadResponse,
)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


UPLOAD_DIR = os.getenv("UPLOAD_DIR", "uploads")
THUMBNAILS_DIR = os.getenv("THUMBNAILS_DIR", "thumbnails")
ALLOWED_EXTENSIONS = {"jpg", "jpeg", "png"}
BASE_URL = os.getenv("BASE_URL", "http://localhost:8000")



@asynccontextmanager
async def lifespan(app: FastAPI):
    """Handle startup and shutdown events."""
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    os.makedirs(THUMBNAILS_DIR, exist_ok=True)

    await connect_to_mongo()
    load_model()
    logger.info("Application started successfully")

    yield


    await close_mongo_connection()
    logger.info("Application shut down gracefully")



app = FastAPI(
    title="Image Processing Pipeline API",
    description="Async image processing backend API.",
    version="1.0.0",
    lifespan=lifespan,
)



def _generate_image_id() -> str:
    """Generate a unique image ID like 'img_a1b2c3d4'."""
    return f"img_{uuid.uuid4().hex[:8]}"


def _get_file_extension(filename: str) -> str:
    """Extract and normalize file extension."""
    return filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def _build_image_response(doc: dict) -> ImageResponse:
    """Build an ImageResponse from a MongoDB document."""
    image_id = doc["image_id"]
    metadata_raw = doc.get("metadata", {})

    metadata = ImageMetadata(
        width=metadata_raw.get("width"),
        height=metadata_raw.get("height"),
        format=metadata_raw.get("format"),
        size_bytes=metadata_raw.get("size_bytes"),
        datetime=metadata_raw.get("datetime"),
        exif=metadata_raw.get("exif"),
        caption=metadata_raw.get("caption"),
    )

    # Only include thumbnail URLs if processing succeeded
    thumbnails = ThumbnailUrls()
    if doc.get("status") == "success":
        thumbnails = ThumbnailUrls(
            small=f"{BASE_URL}/api/images/{image_id}/thumbnails/small",
            medium=f"{BASE_URL}/api/images/{image_id}/thumbnails/medium",
        )

    data = ImageData(
        image_id=image_id,
        original_name=doc.get("original_name", ""),
        processed_at=doc.get("processed_at"),
        metadata=metadata,
        thumbnails=thumbnails,
    )

    return ImageResponse(
        status=doc.get("status", "pending"),
        data=data,
        error=doc.get("error"),
    )




@app.get("/health", tags=["Health"])
async def health_check():
    """Health check endpoint."""
    return {"status": "ok"}


@app.post("/api/images", response_model=UploadResponse, status_code=202, tags=["Images"])
async def upload_image(file: UploadFile = File(...)):
    """Upload an image and queue it for async processing."""
    # Check file extension
    extension = _get_file_extension(file.filename)
    if extension not in ALLOWED_EXTENSIONS:
        # Still record the failed upload in the database
        image_id = _generate_image_id()
        db = get_database()
        await db.images.insert_one({
            "image_id": image_id,
            "original_name": file.filename,
            "status": "failed",
            "metadata": {},
            "thumbnail_paths": {},
            "created_at": datetime.now(timezone.utc).isoformat(),
            "processed_at": datetime.now(timezone.utc).isoformat(),
            "processing_time_seconds": 0,
            "error": f"Invalid file format: .{extension}. Supported formats: JPG, PNG",
        })
        raise HTTPException(
            status_code=422,
            detail=f"Invalid file format: .{extension}. Supported formats: JPG, PNG",
        )

    # Save original file
    image_id = _generate_image_id()
    file_path = os.path.join(UPLOAD_DIR, f"{image_id}.{extension}")

    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    logger.info("Saved uploaded file: %s -> %s", file.filename, file_path)

    # Verify integrity
    try:
        with Image.open(file_path) as img:
            img.verify()
    except Exception:
        os.remove(file_path)
        # Record failure
        db = get_database()
        await db.images.insert_one({
            "image_id": image_id,
            "original_name": file.filename,
            "status": "failed",
            "metadata": {},
            "thumbnail_paths": {},
            "created_at": datetime.now(timezone.utc).isoformat(),
            "processed_at": datetime.now(timezone.utc).isoformat(),
            "processing_time_seconds": 0,
            "error": "File is corrupted or not a valid image.",
        })
        raise HTTPException(
            status_code=422,
            detail="File is corrupted or not a valid image.",
        )

    # Create DB record
    db = get_database()
    await db.images.insert_one({
        "image_id": image_id,
        "original_name": file.filename,
        "status": "pending",
        "metadata": {},
        "thumbnail_paths": {},
        "created_at": datetime.now(timezone.utc).isoformat(),
        "processed_at": None,
        "processing_time_seconds": None,
        "error": None,
    })

    # Dispatch to Celery
    process_image_task.delay(image_id, file_path)

    return UploadResponse(
        status="accepted",
        message="Image uploaded and queued for processing",
        data={"image_id": image_id},
    )


@app.get("/api/images", response_model=list[ImageResponse], tags=["Images"])
async def list_images(
    page: int = Query(1, ge=1, description="Page number"),
    limit: int = Query(20, ge=1, le=100, description="Items per page")
):
    """List all processed or processing images with pagination."""
    db = get_database()
    skip = (page - 1) * limit
    
    cursor = db.images.find({}).sort("created_at", -1).skip(skip).limit(limit)
    documents = await cursor.to_list(length=limit)

    return [_build_image_response(doc) for doc in documents]


@app.get("/api/images/{image_id}", response_model=ImageResponse, tags=["Images"])
async def get_image(image_id: str):
    """Get specific image details including metadata and thumbnail URLs."""
    db = get_database()
    doc = await db.images.find_one({"image_id": image_id})

    if not doc:
        raise HTTPException(status_code=404, detail="Image not found")

    return _build_image_response(doc)


@app.delete("/api/images/{image_id}", status_code=204, tags=["Images"])
async def delete_image(image_id: str):
    """Delete an image, its database record, and all generated thumbnails."""
    db = get_database()
    doc = await db.images.find_one({"image_id": image_id})

    if not doc:
        raise HTTPException(status_code=404, detail="Image not found")

    # 1. Delete original file
    extension = _get_file_extension(doc.get("original_name", ""))
    original_file_path = os.path.join(UPLOAD_DIR, f"{image_id}.{extension}")
    if os.path.exists(original_file_path):
        os.remove(original_file_path)
        logger.info("Deleted original file: %s", original_file_path)

    # 2. Delete thumbnails
    thumbnails = doc.get("thumbnail_paths", {})
    for size, path in thumbnails.items():
        if path and os.path.exists(path):
            os.remove(path)
            logger.info("Deleted thumbnail (%s): %s", size, path)

    # 3. Delete database record
    await db.images.delete_one({"image_id": image_id})
    logger.info("Deleted database record for %s", image_id)

    return


@app.get("/api/images/{image_id}/thumbnails/{size}", tags=["Images"])
async def get_thumbnail(image_id: str, size: str):
    """Return a thumbnail image file ('small' or 'medium')."""
    if size not in ("small", "medium"):
        raise HTTPException(
            status_code=400,
            detail="Invalid thumbnail size. Use 'small' or 'medium'.",
        )

    db = get_database()
    doc = await db.images.find_one({"image_id": image_id})

    if not doc:
        raise HTTPException(status_code=404, detail="Image not found")

    if doc.get("status") != "success":
        raise HTTPException(
            status_code=404,
            detail=f"Thumbnails not available. Image status: {doc.get('status')}",
        )

    thumbnail_paths = doc.get("thumbnail_paths", {})
    thumb_path = thumbnail_paths.get(size)

    if not thumb_path or not os.path.exists(thumb_path):
        raise HTTPException(status_code=404, detail="Thumbnail file not found")

    return FileResponse(
        path=thumb_path,
        media_type="image/jpeg",
        filename=f"{image_id}_{size}.jpg",
    )


@app.get("/api/stats", response_model=StatsResponse, tags=["Statistics"])
async def get_stats():
    """Get system-wide processing statistics."""
    db = get_database()

    total = await db.images.count_documents({})
    failed = await db.images.count_documents({"status": "failed"})
    successful = await db.images.count_documents({"status": "success"})

    # Calculate success rate
    if total > 0:
        success_rate = f"{(successful / total * 100):.2f}%"
    else:
        success_rate = "0.00%"

    # Avg processing time (completed only)
    pipeline = [
        {"$match": {"processing_time_seconds": {"$ne": None}}},
        {"$group": {"_id": None, "avg_time": {"$avg": "$processing_time_seconds"}}},
    ]
    result = await db.images.aggregate(pipeline).to_list(length=1)
    
    avg_time = 0.0
    if result and result[0].get("avg_time") is not None:
        avg_time = round(result[0]["avg_time"], 2)

    return StatsResponse(
        total=total,
        failed=failed,
        success_rate=success_rate,
        average_processing_time_seconds=avg_time,
    )

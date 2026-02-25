
import os
import time
import logging
from datetime import datetime, timezone

from celery import Celery
from celery.signals import worker_process_init

from app.image_processor import generate_thumbnails, extract_metadata, extract_exif
from app.captioner import generate_caption, load_model

logger = logging.getLogger(__name__)


celery_app = Celery(
    "image_pipeline_worker",
    broker=os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0"),
    backend=os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/0"),
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
)

@worker_process_init.connect
def init_worker(**kwargs):
    """Load the ML model once per worker process."""
    logger.info("Initializing worker process: loading BLIP model...")
    load_model()

# Global sync DB client
_sync_db = None


def _get_sync_db():
    """Create a new synchronous MongoDB connection for the worker."""
    global _sync_db
    if _sync_db is None:
        from pymongo import MongoClient

        mongodb_uri = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
        db_name = os.getenv("DATABASE_NAME", "image_pipeline")
        client = MongoClient(mongodb_uri)
        _sync_db = client[db_name]
    return _sync_db


@celery_app.task(bind=True, max_retries=3, default_retry_delay=5)
def process_image_task(self, image_id: str, image_path: str):
    """Celery task to process a single image."""
    db = _get_sync_db()
    start_time = time.time()

    try:
        # Update status to processing
        db.images.update_one(
            {"image_id": image_id},
            {"$set": {"status": "processing"}},
        )
        logger.info("Processing image %s from %s", image_id, image_path)

        # 1. Thumbnails
        logger.info("[%s] Generating thumbnails...", image_id)
        thumbnail_paths = generate_thumbnails(image_path, image_id)

        # 2. Metadata
        logger.info("[%s] Extracting metadata...", image_id)
        metadata = extract_metadata(image_path)

        # 3. EXIF data
        logger.info("[%s] Extracting EXIF data...", image_id)
        exif_data = extract_exif(image_path)

        # 4. AI Caption
        logger.info("[%s] Generating AI caption...", image_id)
        caption = generate_caption(image_path)

        # Calculate processing time
        processing_time = round(time.time() - start_time, 2)

        # Update document with results
        db.images.update_one(
            {"image_id": image_id},
            {
                "$set": {
                    "status": "success",
                    "metadata": {
                        **metadata,
                        "exif": exif_data,
                        "caption": caption,
                    },
                    "thumbnail_paths": thumbnail_paths,
                    "processed_at": datetime.now(timezone.utc).isoformat(),
                    "processing_time_seconds": processing_time,
                    "error": None,
                }
            },
        )

        logger.info(
            "Successfully processed %s in %.2fs", image_id, processing_time
        )
        return {"status": "success", "image_id": image_id}

    except Exception as exc:
        processing_time = round(time.time() - start_time, 2)
        error_msg = str(exc)
        logger.error("Failed to process %s: %s", image_id, error_msg)

        if self.request.retries >= self.max_retries:
            # Final retry exhausted — mark as permanently failed
            db.images.update_one(
                {"image_id": image_id},
                {
                    "$set": {
                        "status": "failed",
                        "processed_at": datetime.now(timezone.utc).isoformat(),
                        "processing_time_seconds": processing_time,
                        "error": error_msg,
                    }
                },
            )
        else:
            # Still have retries left — keep status as processing
            db.images.update_one(
                {"image_id": image_id},
                {"$set": {"status": "processing", "error": f"Retrying: {error_msg}"}},
            )

        # Retry with exponential backoff via Celery
        raise self.retry(exc=exc, countdown=2 ** self.request.retries)

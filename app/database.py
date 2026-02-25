"""
MongoDB connection and database setup using motor (async driver).
"""

import os
import logging
from motor.motor_asyncio import AsyncIOMotorClient

logger = logging.getLogger(__name__)

MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017")
DATABASE_NAME = os.getenv("DATABASE_NAME", "image_pipeline")

client: AsyncIOMotorClient = None
db = None


async def connect_to_mongo():
    """Connect to MongoDB."""
    global client, db
    logger.info("Connecting to MongoDB at %s", MONGODB_URI)
    client = AsyncIOMotorClient(MONGODB_URI)
    db = client[DATABASE_NAME]

    # Ensure unique index on image_id
    await db.images.create_index("image_id", unique=True)
    logger.info("Connected to MongoDB database: %s", DATABASE_NAME)


async def close_mongo_connection():
    """Close MongoDB."""
    global client
    if client:
        client.close()
        logger.info("Closed MongoDB connection")


def get_database():
    """Get DB instance."""
    return db

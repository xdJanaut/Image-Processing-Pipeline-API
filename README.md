# Image Processing Pipeline API

A lightweight, asynchronous backend service for processing images. Built with FastAPI, Celery, Redis, and MongoDB.

This pipeline takes an uploaded image, instantly queues it for background processing, and lets the user go about their day. Behind the scenes, a worker picks up the job, generates multiple thumbnails, extracts EXIF/metadata, and runs the image through a local AI model (Salesforce BLIP) to generate a descriptive text caption.

## Core Flow

1. **Upload:** Client hits `POST /api/images` with a file. The API validates the file, saves it, creates a `pending` DB record, and tosses the job onto a Redis message queue.
2. **Processing:** A Celery worker independently pulls the job off the queue. It systematically creates 150x150 and 300x300 thumbnails, extracts the dimensions/EXIF data, and queries the local AI model for a caption.
3. **Completion:** The worker flags the DB record as `success` (or `failed` if something crashes, with built-in retries).
4. **Retrieval:** The client can query `GET /api/images/<id>` to grab the final JSON payload and thumbnail links.

## How to run it

The easiest way to get this running is with Docker Compose.

```bash
# Clone the repo and cd in
git clone <your-repo-url>
cd image-processing-pipeline

# Spin everything up
docker compose up --build
```

The API will be live at `http://localhost:8000`. 

*Note:* The very first time you run this, it will take a few minutes because it has to download the BLIP model weights (which are around 1.8GB).

To shut it down:
```bash
docker compose down
```

### Running locally (without Docker)

If you prefer to run it without Docker:
1. Make sure you have Python 3.12+ and a local MongoDB instance running on default port 27017.
2. Set up a virtual env and install the requirements:
   ```bash
   python3 -m venv venv
   source venv/bin/activate
   pip install -r requirements.txt
   ```
3. Start it up:
   ```bash
   uvicorn app.main:app --reload
   ```

## Using the API

You can check out the interactive Swagger docs at `http://localhost:8000/docs` once the server is up. Here's a quick rundown of the main endpoints:

### Upload an image
```bash
curl -X POST -F "file=@photo.jpg" http://localhost:8000/api/images
```
You'll get a background job ID back immediately.

### List all images
```bash
curl http://localhost:8000/api/images
```

### Get a specific image's details
```bash
curl http://localhost:8000/api/images/img_a1b2c3d4
```

This returns all the extracted metadata, the AI caption, and links to the thumbnails once the background processing is done. Example output:
```json
{
  "status": "success",
  "data": {
    "image_id": "img_a1b2c3d4",
    "original_name": "photo.jpg",
    "processed_at": "2024-03-10T10:00:00Z",
    "metadata": {
      "width": 1920,
      "height": 1080,
      "format": "jpeg",
      "size_bytes": 2048576,
      "caption": "a scenic mountain landscape with a lake"
    },
    "thumbnails": {
      "small": "http://localhost:8000/api/images/img_a1b2c3d4/thumbnails/small",
      "medium": "http://localhost:8000/api/images/img_a1b2c3d4/thumbnails/medium"
    }
  },
  "error": null
}
```

### Download a thumbnail
```bash
curl http://localhost:8000/api/images/img_a1b2c3d4/thumbnails/small -o thumb.jpg
```
(Change `small` to `medium` if you want the 300x300 version).

### Check overall stats
```bash
curl http://localhost:8000/api/stats
```
This gives you a quick look at how many images were processed successfully, failure rates, and average processing times.

## Running the tests

If you want to run the test suite, just use pytest:
```bash
pip install -r requirements.txt
pytest tests/ -v
```

The tests use `mongomock-motor` so you don't actually need a real Mongo database running for them to pass.

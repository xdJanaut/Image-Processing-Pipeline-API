
import logging
from PIL import Image
from transformers import BlipProcessor, BlipForConditionalGeneration

logger = logging.getLogger(__name__)

MODEL_NAME = "Salesforce/blip-image-captioning-large"

# Global model singletons
_processor = None
_model = None


def load_model():
    """Load BLIP model (startup only)."""
    global _processor, _model

    logger.info("Loading BLIP captioning model: %s", MODEL_NAME)
    logger.info("This may take a few minutes on the first run (downloading model weights)...")

    _processor = BlipProcessor.from_pretrained(MODEL_NAME)
    _model = BlipForConditionalGeneration.from_pretrained(MODEL_NAME)

    logger.info("BLIP model loaded successfully")


def generate_caption(image_path: str) -> str:
    """Generate a descriptive text caption for an image using the local BLIP model."""
    if _processor is None or _model is None:
        raise RuntimeError(
            "BLIP model not loaded. Call load_model() first."
        )

    logger.info("Generating caption for %s", image_path)

    image = Image.open(image_path).convert("RGB")


    inputs = _processor(image, return_tensors="pt")
    output = _model.generate(**inputs, max_new_tokens=50)
    caption = _processor.decode(output[0], skip_special_tokens=True)

    logger.info("Generated caption: '%s'", caption)
    return caption

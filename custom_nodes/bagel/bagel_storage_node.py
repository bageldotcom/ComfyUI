import os
import aiohttp
import asyncio
import io
from pathlib import Path
from .bagel_logging_config import get_bagel_logger

logger = get_bagel_logger("bagel.storage_node")
from PIL import Image
import numpy as np
import uuid
from datetime import datetime

# Configure backend URL from environment (default: localhost for self-hosted)
BAGEL_BACKEND_URL = os.getenv("BAGEL_BACKEND_URL", "http://localhost:8088")

# Dual-mode API Key support:
# 1. Multi-user (Bagel-hosted): API keys injected via X-Bagel-Api-Key header
# 2. Self-hosted: API key from environment or file
try:
    from .save_api_key_middleware import get_api_key_for_user
    logger.debug(f"[BagelStorageNode] Multi-user mode enabled")
except ImportError:
    # Fallback for self-hosted installations
    logger.debug(f"[BagelStorageNode] Self-hosted mode (no middleware)")
    def get_api_key_for_user(user_id=None):
        api_key = os.getenv("BAGEL_API_KEY")
        if not api_key:
            api_key_file = Path.home() / "bagel_api_key.txt"
            if api_key_file.exists():
                api_key = api_key_file.read_text().strip()
        return api_key

# Log backend URL on import
logger.debug(f"[BagelStorageNode] Backend URL: {BAGEL_BACKEND_URL}")

class BagelStorageNode:
    """
    Custom ComfyUI node: Upload image to Bagel S3

    Takes a ComfyUI image tensor and uploads to S3, returns URL
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "image": ("IMAGE",),  # Input from previous node
                "user_id": ("STRING", {"default": "system"}),
                "filename_prefix": ("STRING", {"default": "comfyui"})
            }
        }

    RETURN_TYPES = ("STRING",)  # Returns S3 URL
    FUNCTION = "upload"
    CATEGORY = "bagel"

    async def upload(self, image, user_id, filename_prefix):
        """
        Upload image tensor to S3 via Bagel backend HTTP API, return URL (async, non-blocking)
        """
        # Get API key (multi-user or self-hosted)
        api_key = get_api_key_for_user()
        if not api_key:
            raise ValueError(
                "BAGEL_API_KEY not found. For self-hosted:\n"
                "1. Set env: export BAGEL_API_KEY='your-key'\n"
                "2. Or file: echo 'your-key' > ~/bagel_api_key.txt\n"
                "Get your key from https://app.bagel.com/api-key"
            )

        # Convert tensor to PIL Image
        # ComfyUI tensor format: [batch, height, width, channels] in range [0, 1]
        image_np = (image[0].cpu().numpy() * 255).astype(np.uint8)
        pil_image = Image.fromarray(image_np)

        # Save to bytes
        buffer = io.BytesIO()
        pil_image.save(buffer, format="PNG")
        buffer.seek(0)

        # Generate filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        unique_id = str(uuid.uuid4())[:8]
        filename = f"{filename_prefix}_{timestamp}_{unique_id}.png"

        try:
            # Upload to S3 via Bagel backend API (async, non-blocking)
            # Prepare multipart form data
            form_data = aiohttp.FormData()
            form_data.add_field('file', buffer.getvalue(), filename=filename, content_type='image/png')
            form_data.add_field('user_id', user_id)
            form_data.add_field('prefix', f"comfyui_outputs/{user_id}")

            # Prepare headers with required API key
            headers = {
                "X-API-KEY": api_key
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{BAGEL_BACKEND_URL}/v1/storage/upload",
                    data=form_data,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=60)  # 1 minute timeout
                ) as response:
                    response.raise_for_status()
                    result = await response.json()
                    url = result["url"]

            return (url,)

        except asyncio.TimeoutError:
            raise Exception(
                f"Bagel backend timeout after 60s. Check if backend is running at {BAGEL_BACKEND_URL}"
            )
        except aiohttp.ClientError as e:
            raise Exception(
                f"Connection/API error: {e}"
            )
        except Exception as e:
            raise Exception(f"Image upload failed: {str(e)}")

# Register node
NODE_CLASS_MAPPINGS = {
    "BagelStorageNode": BagelStorageNode
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "BagelStorageNode": "Bagel S3 Upload"
}

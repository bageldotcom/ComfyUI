import os
import requests
import io
import logging
from pathlib import Path
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
    logging.info(f"[BagelStorageNode] Multi-user mode enabled")
except ImportError:
    # Fallback for self-hosted installations
    logging.info(f"[BagelStorageNode] Self-hosted mode (no middleware)")
    def get_api_key_for_user(user_id=None):
        api_key = os.getenv("BAGEL_API_KEY")
        if not api_key:
            api_key_file = Path.home() / "bagel_api_key.txt"
            if api_key_file.exists():
                api_key = api_key_file.read_text().strip()
        return api_key

# Log backend URL on import
logging.info(f"[BagelStorageNode] Backend URL: {BAGEL_BACKEND_URL}")

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

    def upload(self, image, user_id, filename_prefix):
        """
        Upload image tensor to S3 via Bagel backend HTTP API, return URL
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
            # Upload to S3 via Bagel backend API
            files = {
                'file': (filename, buffer.getvalue(), 'image/png')
            }
            data = {
                'user_id': user_id,
                'prefix': f"comfyui_outputs/{user_id}"
            }

            # Prepare headers with required API key
            headers = {
                "Authorization": f"Bearer {api_key}"
            }

            response = requests.post(
                f"{BAGEL_BACKEND_URL}/v1/storage/upload",
                files=files,
                data=data,
                headers=headers,
                timeout=60  # 1 minute timeout for upload
            )
            response.raise_for_status()

            # Parse response
            result = response.json()
            url = result["url"]

            return (url,)

        except requests.exceptions.Timeout:
            raise Exception(
                f"Bagel backend timeout after 60s. Check if backend is running at {BAGEL_BACKEND_URL}"
            )
        except requests.exceptions.ConnectionError:
            raise Exception(
                f"Cannot connect to Bagel backend at {BAGEL_BACKEND_URL}. Is the service running?"
            )
        except requests.exceptions.HTTPError as e:
            raise Exception(
                f"Bagel API error {e.response.status_code}: {e.response.text}"
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

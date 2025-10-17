import os
import requests
import logging
import tempfile
from pathlib import Path

# Configure backend URL from environment (default: localhost for self-hosted)
BAGEL_BACKEND_URL = os.getenv("BAGEL_BACKEND_URL", "http://localhost:8088")

# Dual-mode API Key support:
# 1. Multi-user (Bagel-hosted): API keys injected via X-Bagel-Api-Key header
# 2. Self-hosted: API key from environment or file
try:
    from .save_api_key_middleware import get_api_key_for_user
    logging.info(f"[BagelSeeDanceNode] Multi-user mode enabled")
except ImportError:
    # Fallback for self-hosted installations
    logging.info(f"[BagelSeeDanceNode] Self-hosted mode (no middleware)")
    def get_api_key_for_user(user_id=None):
        api_key = os.getenv("BAGEL_API_KEY")
        if not api_key:
            api_key_file = Path.home() / "bagel_api_key.txt"
            if api_key_file.exists():
                api_key = api_key_file.read_text().strip()
        return api_key

# Log backend URL on import
logging.info(f"[BagelSeeDanceNode] Backend URL: {BAGEL_BACKEND_URL}")

class BagelSeeDanceNode:
    """
    Custom ComfyUI node: Call BytePlus SeeDance video generation

    This node integrates BytePlus SeeDance video generation into ComfyUI workflows.
    It calls the existing SeeDanceVideoAdapter.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "prompt": ("STRING", {"multiline": True, "default": "a person dancing in a park"}),
                "duration": ("INT", {"default": 5, "min": 5, "max": 10}),
                "aspect_ratio": (["16:9", "4:3", "1:1", "9:16", "3:4", "21:9"], {"default": "16:9"}),
                "quality": (["480p", "720p", "1080p"], {"default": "1080p"}),
                "user_id": ("STRING", {"default": "system"})
            },
            "optional": {
                "api_key": ("STRING", {"default": "", "multiline": False})
            }
        }

    RETURN_TYPES = ("VIDEO",)
    FUNCTION = "generate_video"
    CATEGORY = "bagel/video"

    def generate_video(self, prompt, duration, aspect_ratio, quality, user_id, api_key=""):
        """
        Generate video using BytePlus SeeDance via Bagel backend HTTP API
        """
        api_key = get_api_key_for_user(user_id=user_id, provided_key=api_key)
        if not api_key:
            raise ValueError(
                "BAGEL_API_KEY not found. For self-hosted:\n"
                "1. Set env: export BAGEL_API_KEY='your-key'\n"
                "2. Or file: echo 'your-key' > ~/bagel_api_key.txt\n"
                "Get your key from https://app.bagel.com/api-key"
            )

        # Build API request payload
        payload = {
            "model": "seedance-1-0-pro",
            "prompt": prompt,
            "user": user_id,
            "duration": duration,
            "aspect_ratio": aspect_ratio,
            "quality": quality
        }

        try:
            # Prepare headers with required API key
            headers = {
                "Authorization": f"Bearer {api_key}"
            }

            # Call Bagel backend API
            response = requests.post(
                f"{BAGEL_BACKEND_URL}/v1/video/generations",
                json=payload,
                headers=headers,
                timeout=600  # 10 minute timeout for video generation
            )
            response.raise_for_status()

            # Parse response
            result = response.json()
            video_url = result["data"][0]["url"]

            # Download video from S3 URL to temporary file
            video_response = requests.get(video_url, timeout=120)
            video_response.raise_for_status()

            # Save to temp file (ComfyUI expects file path for videos)
            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
            temp_file.write(video_response.content)
            temp_file.close()

            # Return video path (ComfyUI's VIDEO type expects a file path)
            return (temp_file.name,)

        except requests.exceptions.Timeout:
            raise Exception(
                f"Bagel backend timeout. Check if backend is running at {BAGEL_BACKEND_URL}"
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
            raise Exception(f"Video generation failed: {str(e)}")

# Register node
NODE_CLASS_MAPPINGS = {
    "BagelSeeDanceNode": BagelSeeDanceNode
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "BagelSeeDanceNode": "Bagel SeeDance (Video)"
}

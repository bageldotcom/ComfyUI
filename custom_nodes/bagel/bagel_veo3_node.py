import os
import aiohttp
import asyncio
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
    logging.info(f"[BagelVeo3Node] Multi-user mode enabled")
except ImportError:
    # Fallback for self-hosted installations
    logging.info(f"[BagelVeo3Node] Self-hosted mode (no middleware)")
    def get_api_key_for_user(user_id=None, provided_key=None):
        if provided_key:
            return provided_key
        api_key = os.getenv("BAGEL_API_KEY")
        if not api_key:
            api_key_file = Path.home() / "bagel_api_key.txt"
            if api_key_file.exists():
                api_key = api_key_file.read_text().strip()
        return api_key

# Log backend URL on import
logging.info(f"[BagelVeo3Node] Backend URL: {BAGEL_BACKEND_URL}")

class BagelVeo3Node:
    """
    Custom ComfyUI node: Call Google Veo-3 video generation

    This node integrates Google Veo-3 video generation into ComfyUI workflows.
    It calls the existing VideoGenerationsAdapter for Veo-3 models.
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "prompt": ("STRING", {"multiline": True, "default": "a beautiful sunset over mountains"}),
                "duration": ("INT", {"default": 5, "min": 4, "max": 8}),
                "aspect_ratio": (["16:9", "9:16"], {"default": "16:9"}),
                "generate_audio": ("BOOLEAN", {"default": True}),
                "user_id": ("STRING", {"default": "system"})
            },
            "optional": {
                "image_url": ("STRING", {"default": ""}),
                "api_key": ("STRING", {"default": "", "multiline": False})
            }
        }

    RETURN_TYPES = ("VIDEO",)
    FUNCTION = "generate_video"
    CATEGORY = "bagel/video"

    async def generate_video(self, prompt, duration, aspect_ratio, generate_audio, user_id, image_url=None, api_key=""):
        """
        Generate video using Google Veo-3 via Bagel backend HTTP API (async, non-blocking)
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
            "model": "veo-3",
            "prompt": prompt,
            "user": user_id,
            "duration": duration,
            "aspect_ratio": aspect_ratio,
            "generate_audio": generate_audio
        }

        # Add image_url if provided (for image-to-video)
        if image_url and image_url.strip():
            payload["image_url"] = image_url

        try:
            # Prepare headers with required API key
            headers = {
                "Authorization": f"Bearer {api_key}"
            }

            async with aiohttp.ClientSession() as session:
                # Step 1: Submit generation request
                async with session.post(
                    f"{BAGEL_BACKEND_URL}/api/v1/instant/generations",
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=30)  # Short timeout for submission
                ) as response:
                    response.raise_for_status()
                    result = await response.json()

                    # Extract generation ID
                    if "request_id" in result:
                        generation_id = result["request_id"]
                    elif "id" in result:
                        generation_id = result["id"]
                    else:
                        raise Exception("No generation ID in response")

                # Step 2: Poll for completion
                max_wait_time = 900  # 15 minutes
                poll_interval = 5  # 5 seconds
                elapsed_time = 0

                while elapsed_time < max_wait_time:
                    await asyncio.sleep(poll_interval)
                    elapsed_time += poll_interval

                    # Poll status using unified endpoint
                    async with session.get(
                        f"{BAGEL_BACKEND_URL}/api/v1/instant/generations/{generation_id}",
                        headers=headers,
                        timeout=aiohttp.ClientTimeout(total=30)
                    ) as status_response:
                        status_response.raise_for_status()
                        status_result = await status_response.json()

                        # Extract status (handle both response formats)
                        status = status_result.get("status") or status_result.get("choices", [{}])[0].get("status")

                        if status == "completed":
                            # Extract video URL (VEO3 uses choices format)
                            if "choices" in status_result:
                                video_url = status_result["choices"][0].get("s3_video_url")
                            elif "video" in status_result:
                                video_url = status_result["video"].get("url")
                            else:
                                raise Exception("No video URL in completed response")

                            # Download video from S3 URL
                            async with session.get(
                                video_url,
                                timeout=aiohttp.ClientTimeout(total=120)
                            ) as video_response:
                                video_response.raise_for_status()
                                video_bytes = await video_response.read()

                            # Save to temp file (ComfyUI expects file path for videos)
                            temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".mp4")
                            temp_file.write(video_bytes)
                            temp_file.close()

                            # Return video path
                            return (temp_file.name,)

                        elif status in ["failed", "content_filtered"]:
                            raise Exception(f"Video generation failed: {status}")

                        # else: status is "in_progress" or "queued" → continue polling

                raise Exception(f"Video generation timed out after {max_wait_time} seconds")

        except asyncio.TimeoutError:
            raise Exception(
                f"Bagel backend timeout. Check if backend is running at {BAGEL_BACKEND_URL}"
            )
        except aiohttp.ClientError as e:
            raise Exception(
                f"Connection/API error: {e}"
            )
        except Exception as e:
            raise Exception(f"Video generation failed: {str(e)}")

# Register node
NODE_CLASS_MAPPINGS = {
    "BagelVeo3Node": BagelVeo3Node
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "BagelVeo3Node": "Bagel Veo-3 (Video)"
}

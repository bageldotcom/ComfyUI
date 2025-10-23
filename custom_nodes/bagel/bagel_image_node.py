import os
import aiohttp
import asyncio
import io
from pathlib import Path
from PIL import Image
import numpy as np
import torch
from .bagel_logging_config import get_bagel_logger

logger = get_bagel_logger("bagel.image_node")

# Configure backend URL from environment (default: localhost for self-hosted)
BAGEL_BACKEND_URL = os.getenv("BAGEL_BACKEND_URL", "http://localhost:8088")

# Dual-mode API Key support:
# 1. Multi-user (Bagel-hosted): API keys injected via X-Bagel-Api-Key header
# 2. Self-hosted: API key from environment or file
try:
    from .save_api_key_middleware import get_api_key_for_user
    logger.debug(f"[BagelImageNode] Multi-user mode enabled")
except ImportError:
    # Fallback for self-hosted installations
    logger.debug(f"[BagelImageNode] Self-hosted mode (no middleware)")
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
logger.debug(f"[BagelImageNode] Backend URL: {BAGEL_BACKEND_URL}")

class BagelImageNode:
    """
    Custom ComfyUI node: Multi-Provider Image Generation

    This node provides access to 50+ image generation models including:
    - FLUX (Pro, Dev, Schnell, Realism)
    - Stable Diffusion (v3.5, v3, SDXL)
    - HiDream, Imagen4, Ideogram
    - ByteDance, WAN, Qwen, and more
    """

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "model": ([
                    # Flux models
                    "flux-pro", "flux-realism", "flux/dev", "flux/schnell",
                    "flux-krea-lora", "flux-pro/v1.1", "flux-pro/v1.1-ultra",
                    "flux-krea/dev", "flux-kontext/pro", "flux-kontext/pro/max",
                    "flux-kontext/pro/multi", "flux-kontext-lora",
                    # HiDream
                    "hidream-i1-full", "hidream-i1-fast", "fal-ai/hidream-i1-dev",
                    # Stable Diffusion
                    "stable-diffusion-v35-large", "stable-diffusion-v3-medium", "sdxl",
                    # Google/Ideogram
                    "imagen4/preview", "ideogram/v2", "imagen4/preview/ultra",
                    "nano-banana", "ideogram/v3/character-edit",
                    # ByteDance
                    "bytedance/dreamina/v3.1/text-to-image",
                    "bytedance/seedream/v3/text-to-image",
                    "bytedance/seedream/v4",
                    # WAN/Qwen (text-to-image only)
                    "wan/v2.2-a14b/text-to-image/lora",
                    "wan/v2.2-5b/text-to-image",
                    "qwen-image",
                    # Others
                    "hunyuan-image/v2.1",
                    "minimax/image-01", "janus",
                    "recraft/v2/text-to-image", "recraft/v3/text-to-image",
                    "fast-lcm-diffusion"
                ], {"default": "flux-pro"}),
                "prompt": ("STRING", {"multiline": True, "default": "a beautiful landscape"}),
                "width": ("INT", {"default": 1024, "min": 512, "max": 2048, "step": 64}),
                "height": ("INT", {"default": 1024, "min": 512, "max": 2048, "step": 64}),
                "num_inference_steps": ("INT", {"default": 28, "min": 1, "max": 100}),
                "guidance_scale": ("FLOAT", {"default": 3.5, "min": 1.0, "max": 20.0, "step": 0.5}),
                "seed": ("INT", {"default": -1, "min": -1, "max": 2**32 - 1}),
                "user_id": ("STRING", {"default": "system"})
            },
            "optional": {
                "api_key": ("STRING", {"default": "", "multiline": False})
            }
        }

    RETURN_TYPES = ("IMAGE",)
    FUNCTION = "generate"
    CATEGORY = "bagel"

    async def generate(self, model, prompt, width, height, num_inference_steps, guidance_scale, seed, user_id, api_key=""):
        """
        Generate image using Bagel's multi-provider API (async, non-blocking)
        """
        # Get API key with 4-tier fallback (provided > encrypted user file > env > global file)
        api_key = get_api_key_for_user(user_id=user_id, provided_key=api_key)

        # Build API request payload (unified instant API)
        payload = {
            "model": model,
            "prompt": prompt,
            "width": width,
            "height": height,
            "num_images": 1,
            "steps": num_inference_steps,
            "guidance_scale": guidance_scale,
            "seed": seed if seed != -1 else None
        }

        try:
            # Prepare headers with API key (user-specific in multi-user mode)
            headers = {
                "X-API-KEY": api_key
            }

            # Call Bagel backend API (async, non-blocking)
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    f"{BAGEL_BACKEND_URL}/api/v1/instant/generations",
                    json=payload,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=600)  # 10 minute timeout
                ) as response:
                    response.raise_for_status()
                    result = await response.json()
                    image_url = result["images"][0]["url"]

                # Download image from S3 URL (async, non-blocking)
                async with session.get(
                    image_url,
                    timeout=aiohttp.ClientTimeout(total=60)
                ) as img_response:
                    img_response.raise_for_status()
                    image_bytes = await img_response.read()
                    image = Image.open(io.BytesIO(image_bytes))

            # Convert PIL Image to ComfyUI tensor format
            # ComfyUI expects: [batch, height, width, channels] in range [0, 1]
            image_np = np.array(image).astype(np.float32) / 255.0
            image_tensor = torch.from_numpy(image_np)[None,]  # Add batch dimension

            return (image_tensor,)

        except asyncio.TimeoutError:
            raise Exception(
                f"Bagel backend timeout after 300s. Check if backend is running at {BAGEL_BACKEND_URL}"
            )
        except aiohttp.ClientError as e:
            raise Exception(
                f"Connection/API error: {e}"
            )
        except Exception as e:
            raise Exception(f"Image generation failed: {str(e)}")

# Register node
NODE_CLASS_MAPPINGS = {
    "BagelImageNode": BagelImageNode
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "BagelImageNode": "Bagel Image Generator"
}

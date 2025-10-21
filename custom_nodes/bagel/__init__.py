"""
Bagel Custom Nodes for ComfyUI

Official ComfyUI integration for Bagel's multi-provider AI generation platform.

IMAGE NODES:
- BagelParisNode: Paris DDM (Bagel's proprietary model)
- BagelImageNode: 50+ image models (FLUX, SDXL, HiDream, Imagen4, etc.)
- BagelStorageNode: Upload images to Bagel S3

VIDEO NODES:
- BagelVeo3Node: Veo-3 video generation
- BagelSeeDanceNode: SeeDance video generation
- BagelWanVideoNode: WAN video generation
- BagelVideoNode: 50+ video models (Kling, Runway, Minimax, Luma, Pika, etc.)
- SaveVideo: Save video to disk utility

API MODULES:
- bagel_model_downloader: Server-side model downloads (NEW)
"""

# Import middleware and user management (loads automatically, no nodes registered)
from . import user_manager
from . import save_api_key_middleware
from . import bagel_model_downloader  # NEW - registers API routes

# Import image nodes
from .bagel_paris_node import NODE_CLASS_MAPPINGS as PARIS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS as PARIS_DISPLAY
from .bagel_image_node import NODE_CLASS_MAPPINGS as IMAGE_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS as IMAGE_DISPLAY
from .bagel_storage_node import NODE_CLASS_MAPPINGS as STORAGE_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS as STORAGE_DISPLAY

# Import video nodes
from .bagel_veo3_node import NODE_CLASS_MAPPINGS as VEO3_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS as VEO3_DISPLAY
from .bagel_seedance_node import NODE_CLASS_MAPPINGS as SEEDANCE_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS as SEEDANCE_DISPLAY
from .bagel_wan_video_node import NODE_CLASS_MAPPINGS as WAN_VIDEO_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS as WAN_VIDEO_DISPLAY
from .bagel_video_node import NODE_CLASS_MAPPINGS as VIDEO_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS as VIDEO_DISPLAY
from .save_video_node import NODE_CLASS_MAPPINGS as SAVE_VIDEO_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS as SAVE_VIDEO_DISPLAY

NODE_CLASS_MAPPINGS = {
    # Image nodes
    **PARIS_MAPPINGS,
    **IMAGE_MAPPINGS,
    **STORAGE_MAPPINGS,
    # Video nodes
    **VEO3_MAPPINGS,
    **SEEDANCE_MAPPINGS,
    **WAN_VIDEO_MAPPINGS,
    **VIDEO_MAPPINGS,
    **SAVE_VIDEO_MAPPINGS
}

NODE_DISPLAY_NAME_MAPPINGS = {
    # Image nodes
    **PARIS_DISPLAY,
    **IMAGE_DISPLAY,
    **STORAGE_DISPLAY,
    # Video nodes
    **VEO3_DISPLAY,
    **SEEDANCE_DISPLAY,
    **WAN_VIDEO_DISPLAY,
    **VIDEO_DISPLAY,
    **SAVE_VIDEO_DISPLAY
}

WEB_DIRECTORY = "./js"

__all__ = ['NODE_CLASS_MAPPINGS', 'NODE_DISPLAY_NAME_MAPPINGS', 'WEB_DIRECTORY']

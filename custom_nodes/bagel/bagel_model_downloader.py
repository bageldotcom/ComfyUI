"""
Bagel Model Downloader - Server-side model downloads from HuggingFace/CivitAI

This module provides API endpoints to download AI models directly to the ComfyUI
server (S3-backed storage) instead of forcing users to download to their laptops.

Features:
- Stream download from HuggingFace/CivitAI to /comfyui/models
- Real-time progress via WebSocket
- Download deduplication (skip if exists)
- Multi-user support with audit trail
- Cancellation support
- Security: whitelist approved model sources

Endpoints:
- POST /bagel/models/download - Start model download
- GET /bagel/models/download/{download_id}/status - Check progress
- POST /bagel/models/download/{download_id}/cancel - Cancel download

Usage:
Auto-loaded by ComfyUI as a custom node. Routes registered via bagel_api_routes.py
"""

import os
import asyncio
import uuid
import time
import hashlib
import tempfile
import shutil
from pathlib import Path
from typing import Dict, Optional
from dataclasses import dataclass, asdict
from datetime import datetime

import aiohttp
from aiohttp import web
import folder_paths
from .bagel_logging_config import get_bagel_logger

logger = get_bagel_logger("bagel.model_downloader")

# Security: Only allow downloads from these sources
ALLOWED_MODEL_SOURCES = [
    'https://huggingface.co/',
    'https://civitai.com/',
    'https://raw.githubusercontent.com/'  # For some ComfyUI custom nodes
]

# Allowed file extensions (prevent uploading arbitrary files)
ALLOWED_EXTENSIONS = {
    '.safetensors', '.sft', '.ckpt', '.pt', '.pth',
    '.bin', '.onnx', '.yaml', '.json'
}

# Maximum file size: 50 GB
MAX_MODEL_SIZE_BYTES = 50 * 1024 * 1024 * 1024

@dataclass
class DownloadInfo:
    """Track download progress"""
    download_id: str
    user_id: str
    url: str
    model_type: str  # "text_encoders", "checkpoints", etc.
    filename: str
    destination_path: str

    status: str  # "pending", "downloading", "completed", "failed", "cancelled"
    progress_bytes: int = 0
    total_bytes: int = 0
    progress_percent: float = 0.0

    started_at: str = ""
    completed_at: str = ""
    error_message: str = ""

    # Cancellation flag
    cancel_requested: bool = False


class ModelDownloadManager:
    """Manages active model downloads"""

    def __init__(self, prompt_server=None):
        self.active_downloads: Dict[str, DownloadInfo] = {}
        self.download_tasks: Dict[str, asyncio.Task] = {}
        self.prompt_server = prompt_server  # For WebSocket progress updates

    def create_download(self, user_id: str, url: str, model_type: str,
                       filename: str) -> DownloadInfo:
        """Create new download task"""
        download_id = str(uuid.uuid4())

        # Determine destination path
        model_dir = folder_paths.get_folder_paths(model_type)[0]
        destination = os.path.join(model_dir, filename)

        download = DownloadInfo(
            download_id=download_id,
            user_id=user_id,
            url=url,
            model_type=model_type,
            filename=filename,
            destination_path=destination,
            status="pending",
            started_at=datetime.utcnow().isoformat()
        )

        self.active_downloads[download_id] = download
        return download

    def get_download(self, download_id: str) -> Optional[DownloadInfo]:
        """Get download info by ID"""
        return self.active_downloads.get(download_id)

    def cancel_download(self, download_id: str) -> bool:
        """Request download cancellation"""
        download = self.active_downloads.get(download_id)
        if download and download.status == "downloading":
            download.cancel_requested = True
            logger.info(f"[Model Download] Cancellation requested: {download_id}")
            return True
        return False

    async def send_progress_update(self, download: DownloadInfo):
        """Send progress update via WebSocket to all connected clients"""
        if self.prompt_server:
            try:
                await self.prompt_server.send("model_download_progress",
                                              asdict(download))
            except Exception as e:
                logger.debug(f"Failed to send progress update: {e}")

    async def download_model(self, download_id: str):
        """
        Async task: Download model from URL to disk

        Streams the file in chunks to handle large models (up to 50GB).
        Sends progress updates via WebSocket every 5%.
        """
        download = self.active_downloads.get(download_id)
        if not download:
            logger.error(f"Download ID not found: {download_id}")
            return

        try:
            download.status = "downloading"
            logger.info(f"[Model Download] Starting: {download.filename} for user {download.user_id}")

            # Create directory if needed
            os.makedirs(os.path.dirname(download.destination_path), exist_ok=True)

            # Stream download
            async with aiohttp.ClientSession() as session:
                async with session.get(download.url) as response:
                    if response.status != 200:
                        raise Exception(f"HTTP {response.status}: {response.reason}")

                    # Get total size
                    download.total_bytes = int(response.headers.get('Content-Length', 0))

                    # Security: Check file size
                    if download.total_bytes > MAX_MODEL_SIZE_BYTES:
                        raise Exception(
                            f"Model too large: {download.total_bytes / 1024**3:.2f} GB "
                            f"(max: {MAX_MODEL_SIZE_BYTES / 1024**3:.0f} GB)"
                        )

                    # Download to local temp file (NOT on S3 mount)
                    # S3 CSI driver doesn't support os.rename() - this works for all storage types
                    temp_fd, temp_local_path = tempfile.mkstemp(
                        suffix='.safetensors',
                        prefix='comfyui_model_',
                        dir='/tmp'
                    )

                    last_progress_percent = 0.0
                    chunk_size = 1024 * 1024  # 1 MB chunks

                    try:
                        with os.fdopen(temp_fd, 'wb') as f:
                            async for chunk in response.content.iter_chunked(chunk_size):
                                # Check cancellation
                                if download.cancel_requested:
                                    download.status = "cancelled"
                                    download.completed_at = datetime.utcnow().isoformat()
                                    os.unlink(temp_local_path)
                                    logger.info(f"[Model Download] Cancelled: {download.filename}")
                                    await self.send_progress_update(download)
                                    return

                                f.write(chunk)
                                download.progress_bytes += len(chunk)

                                # Calculate progress
                                if download.total_bytes > 0:
                                    download.progress_percent = (
                                        download.progress_bytes / download.total_bytes * 100
                                    )

                                    # Send update every 5%
                                    if download.progress_percent - last_progress_percent >= 5.0:
                                        logger.debug(
                                            f"[Model Download] Progress: {download.filename} "
                                            f"- {download.progress_percent:.1f}% "
                                            f"({download.progress_bytes / 1024**3:.2f} / "
                                            f"{download.total_bytes / 1024**3:.2f} GB)"
                                        )
                                        last_progress_percent = download.progress_percent
                                        await self.send_progress_update(download)

                        # Move complete file to final S3 location (works across filesystems)
                        shutil.move(temp_local_path, download.destination_path)
                    except Exception as temp_error:
                        # Clean up temp file on error
                        if os.path.exists(temp_local_path):
                            os.unlink(temp_local_path)
                        raise temp_error

                    download.status = "completed"
                    download.progress_percent = 100.0
                    download.completed_at = datetime.utcnow().isoformat()

                    logger.info(
                        f"[Model Download] Completed: {download.filename} "
                        f"({download.total_bytes / 1024**3:.2f} GB) "
                        f"for user {download.user_id}"
                    )

                    # Final progress update
                    await self.send_progress_update(download)

        except Exception as e:
            download.status = "failed"
            download.error_message = str(e)
            download.completed_at = datetime.utcnow().isoformat()

            logger.error(f"[Model Download] Failed: {download.filename} - {e}", exc_info=True)
            await self.send_progress_update(download)

            # Clean up temp file
            temp_path = f"{download.destination_path}.tmp"
            if os.path.exists(temp_path):
                os.remove(temp_path)


# Global manager instance (initialized by route registration)
download_manager: Optional[ModelDownloadManager] = None


def validate_model_url(url: str, filename: str) -> tuple[bool, str]:
    """
    Validate model URL and filename for security

    Returns: (is_valid, error_message)
    """
    # Check source whitelist
    if not any(url.startswith(source) for source in ALLOWED_MODEL_SOURCES):
        return False, (
            f"Download blocked: URL source not allowed. "
            f"Only HuggingFace, CivitAI, and GitHub are permitted. "
            f"Got: {url[:100]}"
        )

    # Check file extension
    ext = os.path.splitext(filename)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        return False, (
            f"Download blocked: File type not allowed. "
            f"Allowed: {', '.join(ALLOWED_EXTENSIONS)}. "
            f"Got: {ext}"
        )

    # Check for path traversal
    if '..' in filename or filename.startswith('/'):
        return False, "Download blocked: Invalid filename (path traversal detected)"

    return True, ""


async def handle_download_model(request: web.Request) -> web.Response:
    """
    POST /bagel/models/download

    Start a model download task.

    Request body:
    {
        "url": "https://huggingface.co/.../model.safetensors",
        "model_type": "text_encoders",  // or "checkpoints", "loras", etc.
        "filename": "t5xxl_fp8_e4m3fn_scaled.safetensors"
    }

    Response:
    {
        "download_id": "uuid",
        "status": "pending",
        "destination_path": "/comfyui/models/text_encoders/..."
    }
    """
    try:
        # Get user ID from auth middleware
        user_id = request.headers.get('X-Comfy-User', 'anonymous')

        # Parse request
        data = await request.json()
        url = data.get('url', '').strip()
        model_type = data.get('model_type', '').strip()
        filename = data.get('filename', '').strip()

        if not url or not model_type or not filename:
            return web.json_response(
                {'error': 'Missing required fields: url, model_type, filename'},
                status=400
            )

        # Validate model type exists in ComfyUI
        if model_type not in folder_paths.folder_names_and_paths:
            return web.json_response(
                {
                    'error': f'Invalid model_type: {model_type}',
                    'valid_types': list(folder_paths.folder_names_and_paths.keys())
                },
                status=400
            )

        # Security validation
        is_valid, error_msg = validate_model_url(url, filename)
        if not is_valid:
            logger.warning(f"[Model Download] Blocked by {user_id}: {error_msg}")
            return web.json_response({'error': error_msg}, status=403)

        # Check if model already exists (deduplication)
        model_dir = folder_paths.get_folder_paths(model_type)[0]
        destination = os.path.join(model_dir, filename)

        if os.path.exists(destination):
            logger.info(f"[Model Download] Already exists (skipped): {filename}")
            return web.json_response({
                'download_id': None,
                'status': 'already_exists',
                'message': f'Model already exists: {filename}',
                'destination_path': destination
            })

        # Create download task
        download = download_manager.create_download(user_id, url, model_type, filename)

        # Start async download (don't await - runs in background)
        task = asyncio.create_task(download_manager.download_model(download.download_id))
        download_manager.download_tasks[download.download_id] = task

        logger.info(
            f"[Model Download] Queued: {filename} ({model_type}) "
            f"by user {user_id} - ID: {download.download_id}"
        )

        return web.json_response({
            'download_id': download.download_id,
            'status': download.status,
            'destination_path': download.destination_path,
            'filename': filename,
            'model_type': model_type
        })

    except Exception as e:
        logger.error(f"[Model Download] API Error: {e}")
        return web.json_response({'error': str(e)}, status=500)


async def handle_download_status(request: web.Request) -> web.Response:
    """
    GET /bagel/models/download/{download_id}/status

    Get current download progress.

    Response:
    {
        "download_id": "uuid",
        "status": "downloading",
        "progress_percent": 45.2,
        "progress_bytes": 2147483648,
        "total_bytes": 4738381824,
        "filename": "model.safetensors",
        "error_message": ""
    }
    """
    download_id = request.match_info['download_id']

    download = download_manager.get_download(download_id)
    if not download:
        return web.json_response({'error': 'Download not found'}, status=404)

    return web.json_response(asdict(download))


async def handle_cancel_download(request: web.Request) -> web.Response:
    """
    POST /bagel/models/download/{download_id}/cancel

    Cancel an in-progress download.

    Response:
    {
        "success": true,
        "message": "Download cancelled"
    }
    """
    download_id = request.match_info['download_id']

    success = download_manager.cancel_download(download_id)

    if success:
        return web.json_response({
            'success': True,
            'message': 'Download cancellation requested'
        })
    else:
        return web.json_response({
            'success': False,
            'message': 'Download not found or already completed'
        }, status=404)


def register_download_routes(app: web.Application, prompt_server):
    """
    Register model download routes with the aiohttp application.

    Called by bagel_api_routes.py during server initialization.
    """
    global download_manager

    try:
        # Initialize manager with WebSocket support
        download_manager = ModelDownloadManager(prompt_server=prompt_server)

        # Register routes
        app.router.add_post("/bagel/models/download", handle_download_model)
        app.router.add_get("/bagel/models/download/{download_id}/status", handle_download_status)
        app.router.add_post("/bagel/models/download/{download_id}/cancel", handle_cancel_download)

        logger.info("[Bagel Model Downloader] Routes registered:")
        logger.info("  POST /bagel/models/download")
        logger.info("  GET /bagel/models/download/{download_id}/status")
        logger.info("  POST /bagel/models/download/{download_id}/cancel")

    except Exception as e:
        logger.error(f"[Bagel Model Downloader] Failed to register routes: {e}")


# ComfyUI node registration (no UI nodes, just API)
NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}

__all__ = ['register_download_routes', 'NODE_CLASS_MAPPINGS', 'NODE_DISPLAY_NAME_MAPPINGS']

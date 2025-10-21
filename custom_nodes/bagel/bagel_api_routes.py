"""
Bagel API Routes - Register custom API endpoints after server initialization

This module provides API endpoints for the Bagel ComfyUI integration,
registered after the server is fully initialized to avoid import order issues.
"""
import os
import logging
import aiohttp
from aiohttp import web
from .save_api_key_middleware import get_api_key_for_user
from .bagel_model_downloader import register_download_routes  # NEW

logger = logging.getLogger(__name__)


async def handle_get_config(request):
    """
    API endpoint: GET /bagel/config

    Returns frontend configuration (URLs, etc.)
    """
    frontend_url = os.getenv("BAGEL_FRONTEND_URL", "https://app.bagel.com")
    backend_url = os.getenv("BAGEL_BACKEND_URL", "https://api.bagel.com")

    return web.json_response({
        "frontend_url": frontend_url,
        "backend_url": backend_url
    })


async def handle_get_api_key(request):
    """
    API endpoint: GET /bagel/api_key/{user_id}

    Returns the decrypted API key for a given user_id.
    Used by JavaScript auto-fill extension.
    """
    user_id = request.match_info['user_id']
    try:
        api_key = get_api_key_for_user(user_id=user_id)
        return web.json_response({"api_key": api_key if api_key else ""})
    except Exception as e:
        # Don't expose error details to client for security
        logger.warning(f"[Bagel] Could not fetch API key for {user_id}: {e}")
        return web.json_response({"api_key": ""})


async def handle_get_current_user(request):
    """
    API endpoint: GET /bagel/current_user

    Returns the current user's Bagel profile data for frontend sync.
    """
    try:
        # Get user from auth middleware headers
        comfy_user_id = request.headers.get('comfy-user')
        api_key = request.headers.get('bagel-api-key')

        if not comfy_user_id:
            return web.json_response(
                {"error": "Not authenticated"},
                status=401
            )

        # Fetch user data from Bagel backend
        user_data = await fetch_bagel_user_data(comfy_user_id, api_key)

        return web.json_response({
            "comfy_user_id": comfy_user_id,
            "username": user_data.get('username', 'User'),
            "email": user_data.get('email', ''),
            "api_key": api_key,
            "creditBalance": user_data.get('credit_balance', 0)  # In cents
        })
    except Exception as e:
        logger.error(f"[Bagel] Could not fetch current user: {e}")
        return web.json_response(
            {"error": "Failed to fetch user"},
            status=500
        )


async def fetch_bagel_user_data(comfy_user_id: str, api_key: str):
    """
    Fetch user data from Bagel backend API.

    Args:
        comfy_user_id: ComfyUI user ID (from session)
        api_key: Bagel API key (from session)

    Returns:
        dict: User data (username, email, credit_balance)
    """
    backend_url = os.getenv('BAGEL_BACKEND_URL', 'http://localhost:8000')

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f'{backend_url}/api/v1/user?user_id={comfy_user_id}',
                headers={'X-API-Key': api_key},
                timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    # Backend returns balance in Bagel credits, convert to USD cents
                    # 25 Bagel credits = 1 USD
                    balance = data.get('balance', 0.0)
                    referral_balance = data.get('referral_balance', 0.0)
                    total_credits = balance + referral_balance
                    usd_dollars = total_credits / 25
                    usd_cents = int(usd_dollars * 100)

                    return {
                        'username': data.get('username', 'User'),
                        'email': data.get('email', ''),
                        'credit_balance': usd_cents  # In USD cents
                    }
                else:
                    logger.warning(f"[Bagel] Backend returned {resp.status}")
                    # Return mock data if backend is unavailable
                    return {
                        'username': comfy_user_id,
                        'email': f'{comfy_user_id}@bagel.com',
                        'credit_balance': 0
                    }
    except Exception as e:
        logger.error(f"[Bagel] Failed to fetch from backend: {e}")
        # Return mock data on error
        return {
            'username': comfy_user_id,
            'email': f'{comfy_user_id}@bagel.com',
            'credit_balance': 0
        }


async def handle_userdata_stub(request):
    """
    Stub handler for ComfyUI userdata endpoints that Bagel doesn't use.
    Returns empty responses to prevent 404 console errors.
    """
    # Check if it's a CSS file request
    if request.path.endswith('.css'):
        return web.Response(text='', content_type='text/css')

    # Check if it's a JSON request
    if request.path.endswith('.json') or 'dir=' in str(request.query_string):
        return web.json_response([])

    # Default: empty JSON object
    return web.json_response({})


def register_routes(app, prompt_server=None):  # MODIFIED: Added prompt_server param
    """
    Register Bagel API routes with the aiohttp application.

    Called by ComfyUI after server initialization.
    """
    try:
        app.router.add_get("/bagel/config", handle_get_config)
        app.router.add_get("/bagel/api_key/{user_id}", handle_get_api_key)
        app.router.add_get("/bagel/current_user", handle_get_current_user)

        # Stub endpoints to prevent console errors for unused ComfyUI features
        app.router.add_get("/api/userdata/user.css", handle_userdata_stub)
        app.router.add_get("/user.css", handle_userdata_stub)
        app.router.add_get("/api/userdata", handle_userdata_stub)
        app.router.add_get("/api/userdata/{path:.*}", handle_userdata_stub)

        logger.info("[Bagel] Registered API endpoints: /bagel/config, /bagel/api_key, /bagel/current_user")

        # NEW: Register model download routes
        if prompt_server:
            register_download_routes(app, prompt_server)
        else:
            logger.warning("[Bagel] Prompt server not provided, model download routes not registered")

    except Exception as e:
        logger.error(f"[Bagel] Failed to register API routes: {e}")


# This will be called by our server.py patch
__all__ = ['register_routes']

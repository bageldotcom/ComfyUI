"""
Bagel API Routes - Register custom API endpoints after server initialization

This module provides API endpoints for the Bagel ComfyUI integration,
registered after the server is fully initialized to avoid import order issues.
"""
import os
import aiohttp
from aiohttp import web
from .save_api_key_middleware import get_api_key_for_user
from .bagel_model_downloader import register_download_routes  # NEW
from .bagel_logging_config import get_bagel_logger

logger = get_bagel_logger("bagel.api_routes")


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
    This endpoint is whitelisted (public) so it validates cookies directly.
    Supports both cookie and query parameter authentication.
    """
    try:
        # Get user from auth middleware headers (if middleware ran)
        comfy_user_id = request.headers.get('comfy-user')
        api_key = request.headers.get('bagel-api-key')

        # Fallback: validate cookie or query parameter directly (when endpoint is whitelisted)
        if not comfy_user_id:
            from .bagel_auth_middleware import validate_session_cookie

            # Check cookie first, then query parameter
            session_token = request.cookies.get('bagel_session') or request.query.get('bagel_session')
            if session_token:
                session_data = validate_session_cookie(session_token)
                if session_data:
                    comfy_user_id = session_data['comfy_user_id']
                    api_key = session_data['api_key']

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
            "creditBalance": user_data.get('credit_balance', 0),  # In cents
            "photo_url": user_data.get('photo_url', '')
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
                    total_credits = data.get('balance', 0.0)  # Already includes referral balance from backend
                    usd_dollars = total_credits / 25
                    usd_cents = int(usd_dollars * 100)

                    photo_url = ''
                    try:
                        async with session.get(
                            f'{backend_url}/api/v1/user/{comfy_user_id}/image',
                            headers={'X-API-Key': api_key},
                            timeout=aiohttp.ClientTimeout(total=5)
                        ) as img_resp:
                            if img_resp.status == 200:
                                image_base64 = await img_resp.text()
                                if image_base64 and image_base64.strip():
                                    photo_url = f'data:image/jpeg;base64,{image_base64}'
                                    logger.debug(f"[Bagel] Photo URL fetched for user {comfy_user_id}")
                                else:
                                    logger.debug(f"[Bagel] Empty photo data for user {comfy_user_id}")
                            else:
                                logger.debug(f"[Bagel] Photo fetch returned {img_resp.status} for user {comfy_user_id}")
                    except Exception as e:
                        logger.warning(f"[Bagel] Failed to fetch image: {e}")

                    return {
                        'username': data.get('username', 'User'),
                        'email': data.get('email', ''),
                        'credit_balance': usd_cents,
                        'photo_url': photo_url
                    }
                else:
                    logger.warning(f"[Bagel] Backend returned {resp.status}")
                    # Return mock data if backend is unavailable
                    return {
                        'username': comfy_user_id,
                        'email': f'{comfy_user_id}@bagel.com',
                        'credit_balance': 0,
                        'photo_url': ''
                    }
    except Exception as e:
        logger.error(f"[Bagel] Failed to fetch from backend: {e}")
        # Return mock data on error
        return {
            'username': comfy_user_id,
            'email': f'{comfy_user_id}@bagel.com',
            'credit_balance': 0,
            'photo_url': ''
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

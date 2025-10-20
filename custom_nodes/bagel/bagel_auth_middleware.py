"""
Bagel Authentication Middleware - Block unauthenticated access to ComfyUI.

Validates two authentication methods:
1. bagel_session cookie (encrypted JSON with expiration)
2. dev_token URL parameter (HMAC-SHA256 signed timestamp)

Redirects to frontend if neither is valid.
"""
import os
import logging
import json
import hmac
import hashlib
from datetime import datetime
from cryptography.fernet import Fernet
from aiohttp import web

logger = logging.getLogger(__name__)

FRONTEND_URL = os.getenv("BAGEL_FRONTEND_URL", "https://app.bagel.com")
ENCRYPTION_KEY = os.getenv("COMFY_SESSION_KEY")
cipher = Fernet(ENCRYPTION_KEY.encode()) if ENCRYPTION_KEY else None

DEV_TOKEN_MAX_AGE = 86400  # 24 hours


def validate_session_cookie(cookie_value: str) -> dict:
    """
    Validate encrypted bagel_session cookie.

    Returns:
        dict with user_id, comfy_user_id, api_key, username if valid
        None if invalid or expired
    """
    if not cipher or not cookie_value:
        return None

    try:
        decrypted = cipher.decrypt(cookie_value.encode())
        session_data = json.loads(decrypted)

        exp_time = datetime.fromisoformat(session_data['exp'])
        if datetime.utcnow() > exp_time:
            logger.debug("[Bagel Auth] Session cookie expired")
            return None

        return {
            'user_id': session_data['uid'],
            'comfy_user_id': session_data['comfy_uid'],
            'api_key': session_data['key'],
            'username': session_data['name']
        }
    except Exception as e:
        logger.error(f"[Bagel Auth] Failed to validate session cookie: {e}")
        return None


def validate_dev_token(token: str) -> bool:
    """
    Validate developer token: timestamp:HMAC-SHA256(timestamp:dev_mode, COMFY_SESSION_KEY)

    Returns:
        True if token is valid and not expired (< 24 hours old)
    """
    if not ENCRYPTION_KEY or not token:
        return False

    try:
        parts = token.split(':', 1)
        if len(parts) != 2:
            return False

        timestamp_str, provided_signature = parts
        timestamp = int(timestamp_str)

        token_age = datetime.utcnow().timestamp() - timestamp
        if token_age > DEV_TOKEN_MAX_AGE or token_age < 0:
            logger.debug(f"[Bagel Auth] Dev token expired (age: {token_age}s)")
            return False

        message = f"{timestamp}:dev_mode"
        expected_signature = hmac.new(
            ENCRYPTION_KEY.encode(),
            message.encode(),
            hashlib.sha256
        ).hexdigest()

        if not hmac.compare_digest(provided_signature, expected_signature):
            logger.warning("[Bagel Auth] Dev token signature mismatch")
            return False

        return True

    except Exception as e:
        logger.error(f"[Bagel Auth] Failed to validate dev token: {e}")
        return False


@web.middleware
async def bagel_auth_middleware(request, handler):
    """
    Enforce authentication for Bagel's ComfyUI server.

    Priority:
    1. Check bagel_session cookie (normal users)
    2. Check dev_token URL parameter (developers)
    3. Block and redirect to frontend
    """
    # Allow public endpoints without authentication
    if (request.path.startswith('/assets/') or
        request.path.startswith('/api/system_stats') or
        request.path.startswith('/bagel/api_key')):
        return await handler(request)

    # PRIORITY 1: Check bagel_session query parameter (localhost cross-port auth)
    session_param = request.query.get('bagel_session')
    if session_param:
        session_data = validate_session_cookie(session_param)
        if session_data:
            new_headers = dict(request.headers)
            new_headers['comfy-user'] = session_data['comfy_user_id']
            new_headers['bagel-api-key'] = session_data['api_key']
            request = request.clone(headers=new_headers)

            logger.info(f"[Bagel Auth] Authenticated via URL param: {session_data['username']} ({session_data['comfy_user_id']})")

            response = await handler(request)

            response.set_cookie(
                'bagel_session',
                session_param,
                domain=None,
                httponly=True,
                secure=False,
                samesite='lax',
                max_age=3600
            )

            return response

    # PRIORITY 2: Check session cookie (normal users with API key)
    session_cookie = request.cookies.get('bagel_session')
    if session_cookie:
        session_data = validate_session_cookie(session_cookie)
        if session_data:
            new_headers = dict(request.headers)
            new_headers['comfy-user'] = session_data['comfy_user_id']
            new_headers['bagel-api-key'] = session_data['api_key']
            request = request.clone(headers=new_headers)

            logger.info(f"[Bagel Auth] Authenticated: {session_data['username']} ({session_data['comfy_user_id']})")
            return await handler(request)

    # PRIORITY 1.5: Check dev_session cookie (developers, set after dev_token validation)
    dev_session_cookie = request.cookies.get('dev_session')
    if dev_session_cookie == 'dev-mode-active':
        dev_user_id = "dev-mode-anonymous"
        new_headers = dict(request.headers)
        new_headers['comfy-user'] = dev_user_id
        request = request.clone(headers=new_headers)

        logger.info(f"[Bagel Auth] Authenticated via dev_session: {dev_user_id}")
        return await handler(request)

    # PRIORITY 2: Check dev_token parameter
    dev_token = request.query.get('dev_token')
    if dev_token:
        is_valid = validate_dev_token(dev_token)
        if is_valid:
            dev_user_id = "dev-mode-anonymous"
            logger.info(f"[Bagel Auth] ✅ Developer mode activated: {dev_user_id}")

            new_headers = dict(request.headers)
            new_headers['comfy-user'] = dev_user_id
            request = request.clone(headers=new_headers)

            # Handle the request
            response = await handler(request)

            # Set dev_session cookie so subsequent API requests don't need the token
            response.set_cookie(
                'dev_session',
                'dev-mode-active',
                domain=None,  # localhost
                httponly=True,
                secure=False,  # localhost doesn't use HTTPS
                samesite='lax',
                max_age=3600  # 1 hour
            )

            return response
        else:
            logger.warning("[Bagel Auth] ❌ Dev token validation failed")

    logger.warning(f"[Bagel Auth] Blocked unauthenticated access to: {request.path}")
    return web.HTTPFound(f"{FRONTEND_URL}/comfyui")


NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}

logger.info(f"[Bagel Auth] Loaded (redirect={FRONTEND_URL}/comfyui)")

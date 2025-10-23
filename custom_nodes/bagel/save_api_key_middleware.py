"""
ComfyUI Middleware - Save API keys per user to disk.

This middleware intercepts HTTP requests to capture and store Bagel API keys
per user for multi-user deployments. It reads the comfy-user and bagel-api-key
headers injected by auth middleware and saves them ENCRYPTED to disk.

Saved to: ~/user_data/{user_id}/bagel_api_key.enc
"""
import os
import json
from pathlib import Path
from cryptography.fernet import Fernet
from aiohttp import web
from .bagel_logging_config import get_bagel_logger

logger = get_bagel_logger("bagel.api_key")

# Encryption key from environment (synced from AWS Secrets Manager)
ENCRYPTION_KEY = os.getenv("COMFY_SESSION_KEY")
cipher = Fernet(ENCRYPTION_KEY.encode()) if ENCRYPTION_KEY else None


def get_api_key_for_user(user_id: str = None, provided_key: str = None) -> str:
    """
    Get Bagel API key with fallback priority (matches SIMPLE_PRODUCTION_SOLUTION.md):

    1. Provided key (from node input) - for external ComfyUI servers
    2. User-specific encrypted key (for Bagel's ComfyUI server)
    3. Global environment variable
    4. Global file ~/bagel_api_key.txt

    Args:
        user_id: User ID (only on Bagel's server)
        provided_key: API key from node input (external servers)

    Returns:
        API key string

    Raises:
        ValueError: If no API key found
    """
    # PRIORITY 1: Provided key (external ComfyUI servers)
    if provided_key and provided_key.strip():
        logger.debug("Using API key from node input (external server mode)")
        return provided_key.strip()

    # PRIORITY 2: User-specific encrypted key (Bagel's server)
    if user_id and user_id != "default":
        encryption_key = os.getenv("COMFY_SESSION_KEY")
        if encryption_key:
            try:
                cipher_local = Fernet(encryption_key.encode())
                user_key_file = Path.home() / "user_data" / user_id / "bagel_api_key.enc"

                if user_key_file.exists():
                    encrypted = user_key_file.read_bytes()
                    decrypted = cipher_local.decrypt(encrypted).decode()
                    logger.debug(f"Using per-user encrypted API key for: {user_id}")
                    return decrypted
            except Exception as e:
                logger.warning(f"Failed to read user API key: {e}")

    # PRIORITY 3: Global environment variable
    global_key = os.getenv("BAGEL_API_KEY")
    if global_key:
        logger.debug("Using BAGEL_API_KEY environment variable")
        return global_key

    # PRIORITY 4: Global file
    global_key_file = Path.home() / "bagel_api_key.txt"
    if global_key_file.exists():
        key = global_key_file.read_text().strip()
        if key:
            logger.debug("Using API key from ~/bagel_api_key.txt")
            return key

    # NO API KEY FOUND
    raise ValueError(
        "Bagel API key not found. Please either:\n"
        "1. Set 'api_key' input in this node\n"
        "2. Set BAGEL_API_KEY environment variable\n"
        "3. Save your API key to ~/bagel_api_key.txt\n"
        "4. If using Bagel's ComfyUI server, ensure you're logged in"
    )


user_manager = None

def set_user_manager(um):
    global user_manager
    user_manager = um

@web.middleware
async def save_api_key_middleware(request, handler):
    """
    Save user's API key to their directory on first request.

    This middleware runs on EVERY request to ComfyUI. It checks if the request
    has comfy-user and bagel-api-key headers (injected by auth middleware after session
    validation), and if so, saves the API key ENCRYPTED to disk.

    The saved key is then used by custom nodes via get_api_key_for_user().
    """
    comfy_user = request.headers.get("comfy-user")
    api_key = request.headers.get("bagel-api-key")

    if comfy_user and api_key and cipher:
        user_data_dir = Path.home() / "user_data" / comfy_user
        user_data_dir.mkdir(parents=True, exist_ok=True)

        users_file = Path.home() / "user_data" / "users.json"
        try:
            if users_file.exists():
                users = json.loads(users_file.read_text())
            else:
                users = {}

            if comfy_user not in users:
                users[comfy_user] = comfy_user
                users_file.write_text(json.dumps(users, indent=2))

                if user_manager and hasattr(user_manager, 'users'):
                    user_manager.users[comfy_user] = comfy_user
                    logger.info(f"[Bagel] Registered user in UserManager: {comfy_user}")
                else:
                    logger.info(f"[Bagel] Registered user in users.json: {comfy_user}")
        except Exception as e:
            logger.error(f"[Bagel] Failed to register user {comfy_user}: {e}")

        api_key_file = user_data_dir / "bagel_api_key.enc"

        try:
            encrypted_new = cipher.encrypt(api_key.encode())

            should_write = False
            if not api_key_file.exists():
                should_write = True
            else:
                try:
                    encrypted_old = api_key_file.read_bytes()
                    decrypted_old = cipher.decrypt(encrypted_old).decode()
                    if decrypted_old != api_key:
                        should_write = True
                except Exception:
                    should_write = True

            if should_write:
                api_key_file.write_bytes(encrypted_new)
                api_key_file.chmod(0o600)
                logger.debug(f"[Bagel] Saved encrypted API key for user: {comfy_user}")

        except Exception as e:
            logger.error(f"[Bagel] Failed to save API key for {comfy_user}: {e}")

        new_headers = dict(request.headers)
        new_headers['comfy-user'] = comfy_user
        request = request.clone(headers=new_headers)

    elif comfy_user and api_key and not cipher:
        logger.warning("[Bagel] bagel-api-key header present but COMFY_SESSION_KEY not set - cannot encrypt!")

    response = await handler(request)

    if comfy_user and comfy_user.strip() and isinstance(response, web.Response):
        response.set_cookie('Comfy-User', comfy_user, max_age=86400, httponly=False)

    return response


# API endpoint handler to return user's decrypted API key for auto-fill
async def get_user_api_key(request):
    user_id = request.match_info['user_id']
    try:
        api_key = get_api_key_for_user(user_id=user_id)
        return web.json_response({"api_key": api_key if api_key else ""})
    except Exception as e:
        logger.error(f"[Bagel] Error fetching API key for {user_id}: {e}")
        return web.json_response({"api_key": ""})


# Register API route after PromptServer is initialized
# def register_api_routes():
#     """Register API routes with PromptServer once it's initialized"""
#     try:
#         if PromptServer.instance is not None:
#             PromptServer.instance.routes.get("/bagel/api_key/{user_id}")(get_user_api_key)
#             logger.info("[Bagel] Registered API endpoint: /bagel/api_key/{user_id}")
#         else:
#             logger.warning("[Bagel] PromptServer.instance is None, cannot register routes yet")
#     except Exception as e:
#         logger.error(f"[Bagel] Failed to register API routes: {e}")


# Try to register routes immediately, but don't fail if PromptServer isn't ready
# try:
#     register_api_routes()
# except Exception as e:
#     logger.warning(f"[Bagel] Could not register API routes during import: {e}")

# ComfyUI expects NODE_CLASS_MAPPINGS even for middleware modules
NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}

logger.info("[Bagel] API key middleware loaded")

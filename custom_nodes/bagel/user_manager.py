"""
ComfyUI User Manager - Extract user from headers.

This module is automatically loaded by ComfyUI as a custom node.
It provides a hook to capture the X-Comfy-User header set by nginx.
"""
import os
from .bagel_logging_config import get_bagel_logger

logger = get_bagel_logger("bagel.user_manager")

# Global variable to store the current user
_current_user = None


def get_current_user():
    """
    Get the current ComfyUI user ID.

    Returns:
        str: User ID from X-Comfy-User header, or None if not in multi-user mode
    """
    return _current_user


def set_current_user(user_id):
    """
    Set the current ComfyUI user ID (called by middleware).

    Args:
        user_id: User ID from X-Comfy-User header
    """
    global _current_user
    _current_user = user_id
    logger.debug(f"[UserManager] Current user set to: {user_id}")


# This module doesn't register any nodes, but ComfyUI will still load it
# The middleware.py will use these functions to set the user
NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}

logger.info("[UserManager] User management module loaded")

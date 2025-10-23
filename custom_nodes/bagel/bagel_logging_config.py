"""
Centralized logging configuration for all Bagel custom nodes.

Environment Variables:
- BAGEL_LOG_LEVEL: DEBUG, INFO, WARNING, ERROR (default: INFO)
- COMFY_ENV: production, test, local (alternative way to set level)
"""

import os
import logging
import sys

# Determine log level from environment
LOG_LEVEL_ENV = os.getenv("BAGEL_LOG_LEVEL", "").upper()
COMFY_ENV = os.getenv("COMFY_ENV", "production").lower()

# Map environment to default log level
ENV_TO_LEVEL = {
    "local": "DEBUG",
    "development": "DEBUG",
    "test": "INFO",
    "staging": "INFO",
    "production": "INFO"
}

# Determine final log level
if LOG_LEVEL_ENV in ["DEBUG", "INFO", "WARNING", "ERROR"]:
    LOG_LEVEL = LOG_LEVEL_ENV
else:
    LOG_LEVEL = ENV_TO_LEVEL.get(COMFY_ENV, "INFO")

LOG_LEVEL_INT = getattr(logging, LOG_LEVEL)

def get_bagel_logger(name: str) -> logging.Logger:
    """
    Get a configured logger for Bagel modules.

    Args:
        name: Module name (e.g., "bagel.auth", "bagel.model_downloader")

    Returns:
        Configured logger instance
    """
    logger = logging.getLogger(name)

    # Only configure if not already configured
    if not logger.handlers:
        logger.setLevel(LOG_LEVEL_INT)

        # Console handler with formatting
        handler = logging.StreamHandler(sys.stdout)
        handler.setLevel(LOG_LEVEL_INT)

        # Format: [timestamp] [LEVEL] [module] message
        formatter = logging.Formatter(
            '%(asctime)s [%(levelname)s] [%(name)s] %(message)s',
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        handler.setFormatter(formatter)

        logger.addHandler(handler)
        logger.propagate = False  # Don't propagate to root logger

    return logger

# Convenience function for checking if debug is enabled
def is_debug_enabled() -> bool:
    """Check if DEBUG logging is enabled."""
    return LOG_LEVEL == "DEBUG"

# Log configuration on import (only once)
_config_logger = logging.getLogger("bagel.config")
_config_logger.setLevel(LOG_LEVEL_INT)
if not _config_logger.handlers:
    _handler = logging.StreamHandler(sys.stdout)
    _handler.setFormatter(logging.Formatter('%(message)s'))
    _config_logger.addHandler(_handler)
    _config_logger.propagate = False

_config_logger.info(f"[Bagel Logging] Level: {LOG_LEVEL} (env: {COMFY_ENV})")

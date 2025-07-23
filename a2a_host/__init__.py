# File: Oppo/a2a_host/__init__.py
# Purpose: Initialize the a2a_host package

import logging
import os
from dotenv import load_dotenv
from pathlib import Path

# Load environment variables from .env file in the project root
# This ensures config is available when modules within this package are imported
project_root = Path(__file__).resolve().parent.parent
env_path = project_root / '.env'
if env_path.exists():
    load_dotenv(dotenv_path=env_path)
else:
    # Basic logging setup if run standalone or .env missing
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(name)s - %(message)s')
    logging.warning(f".env file not found at {env_path}. Relying on system environment variables.")

# Configure logging for the package based on loaded env var
# This will be the central configuration point for logging format/level
try:
    from .config import LOG_LEVEL # Import LOG_LEVEL after loading .env
    log_level_to_set = getattr(logging, LOG_LEVEL, logging.INFO)
except ImportError:
    log_level_env = os.getenv("LOG_LEVEL", "INFO").upper()
    log_level_to_set = getattr(logging, log_level_env, logging.INFO)

logging.basicConfig(
    level=log_level_to_set,
    format='%(asctime)s - %(name)s:%(lineno)d - %(levelname)s - %(message)s',
    force=True # Override basicConfig if called previously
)

# Reduce verbosity of noisy libraries commonly used
logging.getLogger("neo4j").setLevel(logging.WARNING)
logging.getLogger("uvicorn").setLevel(logging.INFO) # Keep INFO for startup/shutdown
logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("googleapiclient").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)
logging.getLogger("telegram.ext").setLevel(logging.WARNING)
logging.getLogger("telegram.bot").setLevel(logging.WARNING)
logging.getLogger("passlib").setLevel(logging.WARNING)


# Define package version
__version__ = "0.1.0"

logger = logging.getLogger(__name__)
logger.info(f"Oppo A2A Host package v{__version__} initialized. Log Level: {LOG_LEVEL}")

# Expose key components if desired (optional)
# from .server import app
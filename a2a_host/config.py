# File: Oppo/a2a_host/config.py
# Purpose: Configuration settings loading

import os
from dotenv import load_dotenv
from pathlib import Path
import logging
from typing import List, Optional

logger = logging.getLogger(__name__)

# Load variables from .env file located in the project root
project_root = Path(__file__).resolve().parent.parent
env_path = project_root / '.env'
if env_path.exists():
    load_dotenv(dotenv_path=env_path)
    logger.debug(f"Loaded environment variables from: {env_path}")
else:
    logger.warning(f".env file not found at {env_path}. Using system environment variables or defaults.")


# --- Core Service URLs ---
MCP_SERVER_URL = os.getenv("MCP_SERVER_URL")
A2A_HOST_INTERNAL_URL = os.getenv("A2A_HOST_INTERNAL_URL", "http://a2a_host:8000") # Default for Docker internal

# --- Database Configuration ---
NEO4J_URI = os.getenv("NEO4J_URI")
NEO4J_USERNAME = os.getenv("NEO4J_USERNAME")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD")

# --- Authentication ---
SECRET_KEY = os.getenv("SECRET_KEY")
INTERNAL_SERVICE_API_KEY = os.getenv("INTERNAL_SERVICE_API_KEY")
ALGORITHM = os.getenv("ALGORITHM", "HS256")
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "60"))

# --- Listener API Keys ---
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

# --- LLM API Keys ---
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") # Load even if commented out in example
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY") # Load even if commented out in example

# --- LLM Configuration ---
# Define valid providers
LLM_PROVIDERS = ["GEMINI", "OPENAI", "ANTHROPIC"]
# Get provider selection from env, default to GEMINI if available
CONTRADICTION_LLM_PROVIDER = os.getenv("CONTRADICTION_LLM_PROVIDER", "GEMINI" if GOOGLE_API_KEY else None)
DISINFO_LLM_PROVIDER = os.getenv("DISINFO_LLM_PROVIDER", "GEMINI" if GOOGLE_API_KEY else None)
FACTCHECK_LLM_PROVIDER = os.getenv("FACTCHECK_LLM_PROVIDER", "GEMINI" if GOOGLE_API_KEY else None)
EVASION_LLM_PROVIDER = os.getenv("EVASION_LLM_PROVIDER", "GEMINI" if GOOGLE_API_KEY else None)
# Get model names from env, with defaults
GEMINI_MODEL_NAME = os.getenv("GEMINI_MODEL_NAME", "gemini-1.5-flash-latest")
OPENAI_MODEL_NAME = os.getenv("OPENAI_MODEL_NAME", "gpt-4o") # Provide default
ANTHROPIC_MODEL_NAME = os.getenv("ANTHROPIC_MODEL_NAME", "claude-3-haiku-20240307") # Provide default

# --- Optional Background Data Collection API Keys ---
FEC_API_KEY = os.getenv("FEC_API_KEY")
OPENSECRETS_API_KEY = os.getenv("OPENSECRETS_API_KEY")
CONGRESS_API_KEY = os.getenv("CONGRESS_API_KEY") # Often not needed

# --- Logging ---
LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO').upper()

# --- A2A Agent Configuration ---
# Load registered agents dynamically if possible, or from env vars
# Example structure - DO NOT HARDCODE SECRETS
REGISTERED_A2A_AGENTS = {}
agent_index = 1
while True:
    endpoint_var = f"AGENT_{agent_index}_ENDPOINT"
    secret_var = f"AGENT_{agent_index}_SECRET"
    endpoint = os.getenv(endpoint_var)
    secret = os.getenv(secret_var)
    if endpoint and secret:
        agent_id = f"agent_{agent_index}" # Simple ID generation
        REGISTERED_A2A_AGENTS[agent_id] = {"endpoint": endpoint, "secret": secret}
        logger.debug(f"Loaded A2A Agent config for {agent_id}")
        agent_index += 1
    else:
        # Stop looking if endpoint or secret is missing for the current index
        break
if not REGISTERED_A2A_AGENTS:
     logger.warning("No A2A Agent endpoints/secrets found in environment variables (e.g., AGENT_1_ENDPOINT, AGENT_1_SECRET). Distribution disabled.")


# --- Validation Checks ---
if not MCP_SERVER_URL:
    logger.error("MCP_SERVER_URL environment variable not set. Internal communication will fail.")
if not NEO4J_URI or not NEO4J_USERNAME or not NEO4J_PASSWORD:
    logger.error("Neo4j connection details (URI, USERNAME, PASSWORD) not fully configured.")
if not SECRET_KEY:
    logger.critical("CRITICAL: SECRET_KEY for JWT not set. Authentication will fail.")
if not INTERNAL_SERVICE_API_KEY:
    logger.warning("INTERNAL_SERVICE_API_KEY not set. Internal API endpoints may be insecure.")
if not GOOGLE_API_KEY and not OPENAI_API_KEY and not ANTHROPIC_API_KEY:
     logger.warning("No LLM API keys (GOOGLE_API_KEY, OPENAI_API_KEY, ANTHROPIC_API_KEY) found. LLM analysis will be disabled.")

logger.info("Configuration loaded.")
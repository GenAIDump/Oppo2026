# File: Oppo/data_collection/__init__.py
# Purpose: Initialize the data_collection package

import logging

logger = logging.getLogger(__name__)
logger.info("Data Collection package initialized.")

# This package contains modules for background data gathering.
# In the v0.1 LLM/MCP architecture, the focus is on listeners,
# but these modules are retained for potential future use or initial data loading.
# Processors within this package should be adapted to send data via MCP Server API calls.

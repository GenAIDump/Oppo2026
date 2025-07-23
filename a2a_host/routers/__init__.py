# File: Oppo/a2a_host/routers/__init__.py
# Purpose: Initialize the routers module and include specific routers

from fastapi import APIRouter

from . import opposition # Import your router files here

# Main API router for external A2A Agents
api_router = APIRouter()

# Include routers from submodules, prefixing them appropriately
api_router.include_router(opposition.router, prefix="/opposition", tags=["Opposition Research"])
# Add other routers here if created (e.g., for subscriptions, admin tasks)

# Optional: Define a root path for this specific API router group
@api_router.get("/", tags=["API Root"], summary="API Root Endpoint")
async def api_sub_root():
    """Provides information about the available API sections."""
    return {"message": "Oppo A2A Host API v0.1", "available_sections": ["/opposition"]}
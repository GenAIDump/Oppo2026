# File: Oppo/a2a_host/routers/opposition.py
# Purpose: Handles standard opposition research requests (on-demand reports) via MCP Server.

import logging
from fastapi import APIRouter, Depends, HTTPException, Query, status
from typing import Optional, Dict, Any

# Import necessary components
try:
    # Import the ReportGenerator which now uses MCP internally
    from analysis import ReportGenerator
    # Import auth dependency
    from ..auth import get_current_active_user, User
    # Import response model if defined centrally, or define here
    from pydantic import BaseModel
    ANALYSIS_LOADED = True
except ImportError as e:
     # Ensure logger is available if config import failed
     log_level_env = os.getenv("LOG_LEVEL", "INFO").upper()
     logging.basicConfig(level=getattr(logging, log_level_env, logging.INFO), format='%(asctime)s:%(levelname)s:%(name)s:%(lineno)d:%(message)s')
     logger = logging.getLogger(__name__)
     logger.error(f"Could not import dependencies for opposition router: {e}")
     ANALYSIS_LOADED = False
     # Define dummy classes if needed
     class ReportGenerator: pass
     class User: pass
     class BaseModel: pass
     def get_current_active_user(): pass


# Configure logger for this module
logger = logging.getLogger(__name__)

router = APIRouter()

# Define response model for the report endpoint
class ReportResponse(BaseModel):
    status: str = "success"
    report: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    message: Optional[str] = None


# Dependency to get ReportGenerator instance (assuming it's initialized in server lifespan)
# This relies on FastAPI's ability to manage state or using a dependency injection framework.
# Accessing it as a global initialized in server.py lifespan.
# A better approach uses Dependency Injection frameworks (like fastapi-injector).
from ..server import report_generator as global_report_generator

async def get_report_generator() -> ReportGenerator:
    if not global_report_generator or not ANALYSIS_LOADED:
         logger.error("ReportGenerator not initialized or analysis modules failed to load.")
         raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="Reporting service not available")
    return global_report_generator


@router.get(
    "/report/{candidate_id}",
    response_model=ReportResponse,
    summary="Get Opposition Research Report",
    description="Retrieves a generated opposition research report for the specified candidate ID, potentially focused on a topic."
    )
async def get_opposition_report_endpoint(
    candidate_id: str,
    topic: Optional[str] = Query(None, description="Optional topic keyword to focus the report context."),
    current_user: User = Depends(get_current_active_user), # Require authentication
    report_gen: ReportGenerator = Depends(get_report_generator) # Get generator instance via dependency
):
    """
    Endpoint for A2A agents to request a generated opposition research report.
    The report generation logic now fetches data via the MCP Server.
    """
    logger.info(f"Received report request for candidate_id: {candidate_id}, topic: {topic} by user: {current_user.username}")

    try:
        # The ReportGenerator's generate_report method handles fetching via MCP
        # Make the call async if the underlying MCP calls are async
        # Assuming generate_report is now async or wrapped
        report_data = await report_gen.generate_report(candidate_id, topic_of_interest=topic) # Assuming generate_report is async

        if report_data is None:
             # Check if this was due to candidate not found vs. other MCP error
             # The ReportGenerator should ideally log the specific reason
             logger.warning(f"Report generation returned None for candidate {candidate_id}, topic {topic}")
             # Return 404 if candidate likely didn't exist or no data found
             raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Could not generate report for candidate '{candidate_id}'. Candidate or relevant data not found.")

        logger.info(f"Successfully generated report for candidate {candidate_id}")
        return ReportResponse(status="success", report=report_data)

    except HTTPException as he:
        # Re-raise known HTTP exceptions (like 404 or 503 from dependencies)
        raise he
    except Exception as e:
        logger.error(f"Failed to generate report for candidate {candidate_id}: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal Server Error generating report")

# Example of adding another endpoint if needed
# @router.get("/candidates/list", ...)
# async def list_tracked_candidates(...): ...
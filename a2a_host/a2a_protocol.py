# File: Oppo/a2a_host/a2a_protocol.py
# Purpose: Defines A2A message formats, handles outgoing distribution logic.

import logging
import requests
import json
import time
import hmac
import hashlib
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

from pydantic import BaseModel, Field, HttpUrl, field_validator

# Import config relative to this file's location within the package
try:
    from .config import REGISTERED_A2A_AGENTS, LOG_LEVEL # Load registered agents
except ImportError:
    # Fallback for standalone use or different structure
    log_level_env = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(level=getattr(logging, log_level_env, logging.INFO), format='%(asctime)s:%(levelname)s:%(name)s:%(lineno)d:%(message)s')
    logger = logging.getLogger(__name__)
    logger.warning("Could not import config from .config. Loading REGISTERED_A2A_AGENTS from environment (if set).")
    # Attempt to reconstruct REGISTERED_A2A_AGENTS from env - less ideal
    REGISTERED_A2A_AGENTS = {}
    agent_index = 1
    while True:
        endpoint_var = f"AGENT_{agent_index}_ENDPOINT"
        secret_var = f"AGENT_{agent_index}_SECRET"
        endpoint = os.getenv(endpoint_var)
        secret = os.getenv(secret_var)
        if endpoint and secret:
            agent_id = f"agent_{agent_index}"
            REGISTERED_A2A_AGENTS[agent_id] = {"endpoint": endpoint, "secret": secret}
            agent_index += 1
        else:
            break
    if not REGISTERED_A2A_AGENTS:
        logger.warning("No A2A Agent endpoints/secrets found in environment variables.")

# Ensure logging is configured
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format='%(asctime)s:%(levelname)s:%(name)s:%(lineno)d:%(message)s',
    force=True
)
logger = logging.getLogger(__name__)


# --- A2A Message Structures (Example using Pydantic v2 syntax) ---

class A2ABaseMessage(BaseModel):
    version: str = Field(default="0.1.0", description="Protocol version")
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    sender_id: str = Field(default="oppo-a2a-host", description="ID of the sending agent")
    # signature: Optional[str] = Field(None, description="HMAC-SHA256 signature of the payload") # Optional

    model_config = {
        "json_encoders": {
            datetime: lambda dt: dt.isoformat(timespec='seconds').replace('+00:00', 'Z')
        }
    }

class A2ARequest(A2ABaseMessage):
    request_id: str = Field(..., description="Unique ID for this request")
    action: str = Field(..., description="Action requested (e.g., 'get_report', 'subscribe_alerts')")
    payload: Dict[str, Any] = Field(default_factory=dict, description="Request-specific data")

class A2AResponse(A2ABaseMessage):
    request_id: str = Field(..., description="ID of the request being responded to")
    status: str = Field(..., description="Status of the request ('success', 'error', 'pending')")
    payload: Optional[Dict[str, Any]] = Field(None, description="Response data (e.g., report content)")
    error_message: Optional[str] = Field(None, description="Error details if status is 'error'")

class A2AAlert(A2ABaseMessage):
    alert_id: str = Field(..., description="Unique ID for this alert")
    alert_type: str = Field(..., description="Type of alert (e.g., 'SIGNIFICANT_POST', 'DISINFO_FLAG_HIGH')")
    payload: Dict[str, Any] = Field(..., description="Alert details (post info, scores, etc.)")


# --- Distribution Logic ---

def sign_message(message_body: str, secret: str) -> str:
    """Generates an HMAC-SHA256 signature for a message body."""
    if not secret:
        logger.warning("Cannot sign message: No secret provided.")
        return ""
    try:
        signature = hmac.new(
            secret.encode('utf-8'),
            message_body.encode('utf-8'),
            hashlib.sha256
        ).hexdigest()
        return signature
    except Exception as e:
        logger.error(f"Error generating HMAC signature: {e}", exc_info=True)
        return ""

class A2ADistributor:
    """Handles formatting and sending alerts to registered A2A agents."""
    def __init__(self):
        # Load registered agents from config (ensure it's loaded)
        self.agents = REGISTERED_A2A_AGENTS
        self.session = requests.Session()
        # TODO: Add signature generation logic if required by protocol standard
        logger.info(f"A2ADistributor initialized with {len(self.agents)} registered agent(s).")

    def format_alert_message(self, post_node_id: str, significance_score: float, disinfo_score: float, reason_flags: List[str], post_data: dict) -> A2AAlert:
        """Formats the analysis results into an A2A Alert message."""
        # Determine alert type based on scores/flags
        alert_type = "SIGNIFICANT_POST" # Default
        if disinfo_score >= 0.8: # Example threshold for high alert
            alert_type = "DISINFO_FLAG_HIGH"
        elif disinfo_score >= 0.6: # Medium threshold
             alert_type = "DISINFO_FLAG_MEDIUM"
        elif "CONTRADICTION" in str(reason_flags).upper(): # Flag contradictions specifically?
             alert_type = "CONTRADICTION_DETECTED"

        # Clean up post_data for payload - avoid sending huge raw data unless needed
        payload_post_data = {
             "platform": post_data.get("source_platform"),
             "platform_post_id": post_data.get("post_id"),
             "content_snippet": (post_data.get("content", "") or "")[:500] + ("..." if len(post_data.get("content", "")) > 500 else ""),
             "post_timestamp_utc": post_data.get("timestamp"), # Should be ISO string already
             "post_url": post_data.get("url"),
             "author_username": post_data.get("author_username"),
             "candidate_name": post_data.get("candidate_name", "Unknown") # Assume added before calling trigger
        }

        alert_payload = {
            "internal_reference_id": post_node_id, # Internal Oppo ID for correlation
            "significance_score": round(significance_score, 3),
            "disinformation_score": round(disinfo_score, 3),
            "analysis_flags": reason_flags, # List of flags from Decision Engine
            "post_details": payload_post_data,
            # Add links to evidence or related items if available from analysis
            # "evidence_urls": analysis_results.get('fact_check', {}).get('fact_check_evidence', [])
        }
        alert = A2AAlert(
            alert_id=f"alert_{int(time.time())}_{post_node_id[:8]}", # Reasonably unique ID
            alert_type=alert_type,
            payload=alert_payload
        )
        return alert

    def send_alert_to_agents(self, alert: A2AAlert):
        """Sends the formatted alert to all registered A2A agents."""
        if not self.agents:
            logger.warning("No registered A2A agents to send alert to.")
            return

        success_count = 0
        # Serialize using Pydantic V2's model_dump_json
        try:
            alert_json_str = alert.model_dump_json()
        except Exception as e:
             logger.error(f"Failed to serialize alert {alert.alert_id}: {e}", exc_info=True)
             return

        total_agents = len(self.agents)
        logger.info(f"Distributing alert {alert.alert_id} ({alert.alert_type}) to {total_agents} agent(s)...")

        for agent_id, agent_info in self.agents.items():
            endpoint = agent_info.get("endpoint")
            secret = agent_info.get("secret") # Used for signing

            if not endpoint:
                logger.warning(f"Agent '{agent_id}' has no endpoint configured. Skipping.")
                continue
            if not secret:
                 logger.warning(f"Agent '{agent_id}' has no secret configured. Cannot sign message. Skipping.")
                 continue

            try:
                signature = sign_message(alert_json_str, secret)
                if not signature:
                     logger.error(f"Failed to sign message for agent '{agent_id}'. Skipping.")
                     continue

                headers = {
                    'Content-Type': 'application/json',
                    'X-Oppo-Signature': f"sha256={signature}" # Example signature header
                    # Add other necessary A2A headers (e.g., Content-Length might be added by requests)
                }

                logger.debug(f"Sending alert {alert.alert_id} to {agent_id} at {endpoint}")
                response = self.session.post(
                    endpoint,
                    data=alert_json_str.encode('utf-8'), # Send bytes
                    headers=headers,
                    timeout=20 # Timeout for external agent response
                )

                # Check response from agent (2xx indicates success)
                if 200 <= response.status_code < 300:
                    logger.info(f"Alert {alert.alert_id} successfully sent to agent '{agent_id}'. Status: {response.status_code}")
                    success_count += 1
                else:
                    logger.error(f"Failed to send alert {alert.alert_id} to agent '{agent_id}'. Status: {response.status_code}, Response: {response.text[:200]}")

            except requests.exceptions.Timeout:
                 logger.error(f"Timeout sending alert {alert.alert_id} to agent '{agent_id}' at {endpoint}.")
            except requests.exceptions.RequestException as e:
                logger.error(f"Network error sending alert {alert.alert_id} to agent '{agent_id}' at {endpoint}: {e}")
            except Exception as e:
                logger.error(f"Unexpected error sending alert {alert.alert_id} to agent '{agent_id}': {e}", exc_info=True)

        logger.info(f"Finished distributing alert {alert.alert_id}. Sent successfully to {success_count}/{total_agents} agents.")

# --- Protocol Handling Trigger (Called from Decision Engine/Server) ---
# Lazy initialize distributor instance to avoid issues during import time
_a2a_distributor_instance: Optional[A2ADistributor] = None

def get_distributor() -> A2ADistributor:
    """Gets the singleton A2ADistributor instance."""
    global _a2a_distributor_instance
    if _a2a_distributor_instance is None:
        _a2a_distributor_instance = A2ADistributor()
    return _a2a_distributor_instance

def trigger_distribution(post_node_id: str, significance_score: float, disinfo_score: float, reason_flags: List[str], post_data: dict):
    """Formats and sends an alert based on analysis results."""
    distributor = get_distributor()
    if not distributor:
        logger.error("A2A Distributor not initialized. Cannot send alert.")
        return

    try:
        # Ensure post_data has necessary fields for formatting
        # Candidate name might need to be added here if not already present
        # Example: if 'candidate_name' not in post_data: post_data['candidate_name'] = fetch_name_via_mcp(post_data['candidate_id'])
        alert_message = distributor.format_alert_message(post_node_id, significance_score, disinfo_score, reason_flags, post_data)
        # Consider running send_alert_to_agents in a background thread/task queue
        # to avoid blocking the caller (e.g., the analysis pipeline in the A2A Host).
        # For simplicity here, it's synchronous.
        distributor.send_alert_to_agents(alert_message)
    except Exception as e:
         logger.error(f"Error during A2A distribution trigger for post {post_node_id}: {e}", exc_info=True)

```python
# File: Oppo/a2a_host/server.py
# Purpose: Main FastAPI application setup, lifespan manager, ingestion endpoint, analysis orchestration.

import logging
import os
from contextlib import asynccontextmanager
from typing import Optional, Dict, Any, List
import asyncio # For triggering async tasks

from fastapi import FastAPI, Depends, HTTPException, Request, status, Body, BackgroundTasks
from fastapi.security import OAuth2PasswordRequestForm
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, ValidationError

# --- Project Imports ---
# Configuration
from .config import (
    MCP_SERVER_URL, INTERNAL_SERVICE_API_KEY, LOG_LEVEL, # URLs and Keys
    CONTRADICTION_LLM_PROVIDER, DISINFO_LLM_PROVIDER, # LLM Choices
    FACTCHECK_LLM_PROVIDER, EVASION_LLM_PROVIDER
)
# Authentication
from .auth import (
    authenticate_user, create_access_token, get_current_active_user, verify_internal_api_key,
    Token, User
)
# API Routers
from .routers import api_router as main_api_router # Main router for external A2A agents
# Database Models (used for request body validation)
try:
    from database.data_models import SocialPost
    MODELS_LOADED = True
except ImportError:
     logging.error("Could not import data models for a2a_host server. Payload validation might fail.")
     MODELS_LOADED = False
     class SocialPost(BaseModel): pass # Dummy model
# Analysis Components (instantiated during lifespan)
from analysis import (
    FactChecker, ContradictionDetector, EvasionDetector,
    DisinformationAnalyzer, DecisionEngine, ReportGenerator,
    LLMInterface # The core LLM interaction layer
)
# A2A Protocol for triggering distribution
from .a2a_protocol import trigger_distribution

# --- Logging Setup ---
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format='%(asctime)s - %(name)s:%(lineno)d - %(levelname)s - %(message)s',
    force=True # Ensure logger is configured
)
logger = logging.getLogger(__name__)


# --- Global State (Managed by Lifespan) ---
# These are initialized at startup
mcp_session: Optional[requests.Session] = None # Session for calling MCP
llm_interface: Optional[LLMInterface] = None
report_generator: Optional[ReportGenerator] = None
fact_checker: Optional[FactChecker] = None
contradiction_detector: Optional[ContradictionDetector] = None
evasion_detector: Optional[EvasionDetector] = None
disinformation_analyzer: Optional[DisinformationAnalyzer] = None
decision_engine: Optional[DecisionEngine] = None

# --- Helper Function for MCP Calls (used by analysis orchestration) ---
async def call_mcp_api(
    method: str,
    endpoint: str,
    json_payload: Optional[Dict] = None,
    params: Optional[Dict] = None
) -> Optional[Dict]:
    """Async helper to call the MCP Server API using the global session."""
    global mcp_session
    if not MCP_SERVER_URL or mcp_session is None:
        logger.error("MCP_SERVER_URL or MCP session not configured/initialized.")
        return {"error": "MCP connection not available"}

    url = f"{MCP_SERVER_URL.rstrip('/')}/{endpoint.lstrip('/')}"
    log_payload_str = f"{str(json_payload)[:200]}..." if json_payload else "None"
    logger.debug(f"MCP Call (from A2A Host): {method.upper()} {url} Params: {params} Payload: {log_payload_str}")
    loop = asyncio.get_running_loop()
    try:
        # Run requests call in a threadpool to avoid blocking asyncio event loop
        response = await loop.run_in_executor(
            None, # Use default executor
            lambda: mcp_session.request(method, url, json=json_payload, params=params, timeout=45) # Longer timeout for potentially complex MCP queries
        )
        response.raise_for_status()
        data = response.json()
        if isinstance(data, dict) and data.get("status") == "success":
            return data
        else:
            error_msg = data.get('message', data.get('detail', 'Unknown MCP error structure')) if isinstance(data, dict) else f"Non-dict response: {str(data)[:200]}"
            logger.error(f"MCP API returned non-success status for {method} {endpoint}: {error_msg}")
            return {"error": error_msg}
    except requests.exceptions.HTTPError as e:
        error_detail = f"HTTP Error {e.response.status_code}"
        try: error_detail = e.response.json().get('detail', error_detail)
        except: pass
        logger.error(f"HTTP Error calling MCP {method} {endpoint}: {error_detail}", exc_info=False)
        return {"error": error_detail}
    except requests.exceptions.RequestException as e:
        logger.error(f"Network Error calling MCP {method} {endpoint}: {e}", exc_info=False)
        return {"error": "Network Error"}
    except Exception as e:
        logger.error(f"Unexpected error calling MCP {method} {endpoint}: {e}", exc_info=True)
        return {"error": "Unexpected Processing Error"}


# --- Analysis Orchestration Task ---
async def run_analysis_pipeline(post_node_id: str, post_payload: Dict):
    """
    Fetches context via MCP, runs all analysis modules using LLM Interface,
    makes a decision, updates MCP, and triggers distribution if needed.
    Designed to be run as a background task.
    """
    global llm_interface, fact_checker, contradiction_detector, evasion_detector, \
           disinformation_analyzer, decision_engine

    logger.info(f"Starting analysis pipeline for post node: {post_node_id}")
    analysis_results = {} # Store results from each module

    # Ensure required components are initialized
    if not all([llm_interface, decision_engine]):
        logger.error(f"Cannot run analysis pipeline for {post_node_id}: Core components (LLM Interface, Decision Engine) not initialized.")
        return

    # --- Fetch Context (Example: fetch related statements/votes via MCP) ---
    candidate_id = post_payload.get('candidate_id')
    context_statements = []
    context_votes = []
    if candidate_id:
        logger.debug(f"Fetching context for candidate {candidate_id} via MCP...")
        stmt_resp = await call_mcp_api('GET', f"/context/statements/{candidate_id}", params={'limit': 10})
        if stmt_resp and not stmt_resp.get('error'): context_statements = stmt_resp.get('statements', [])
        vote_resp = await call_mcp_api('GET', f"/context/votes/{candidate_id}", params={'limit': 20})
        if vote_resp and not vote_resp.get('error'): context_votes = vote_resp.get('votes', [])
        logger.debug(f"Fetched context: {len(context_statements)} statements, {len(context_votes)} votes.")
    else:
         logger.warning(f"Cannot fetch context for post {post_node_id}: candidate_id missing in payload.")

    # --- Run Analysis Modules (using LLM Interface) ---
    # Each analyzer uses the LLM interface internally
    try:
        if contradiction_detector:
            analysis_results['contradiction'] = await contradiction_detector.analyze_new_post_contradictions_llm(
                candidate_id=candidate_id, # Pass candidate ID for context fetching
                new_post_content=post_payload.get('content',''),
                historical_statements=context_statements, # Pass fetched context
                historical_votes=context_votes
            )
        if evasion_detector:
            analysis_results['evasion'] = await evasion_detector.analyze_evasiveness_llm(
                text_content=post_payload.get('content','')
            )
        if fact_checker:
            analysis_results['fact_check'] = await fact_checker.check_statement_llm(
                text_content=post_payload.get('content','')
            )
        if disinformation_analyzer:
            analysis_results['disinformation'] = await disinformation_analyzer.analyze_post_llm(
                post_data=post_payload, # Pass full post data
                context_statements=context_statements # Pass context
            )

        logger.info(f"Completed analysis modules for post node: {post_node_id}")
        logger.debug(f"Analysis results for {post_node_id}: {analysis_results}")

        # --- Make Decision ---
        # Decision engine combines results and updates MCP
        decision_outcome = decision_engine.make_decision(
            post_node_id=post_node_id,
            post_data=post_payload, # Pass original post data for distribution context
            analysis_results=analysis_results
        )
        logger.info(f"Decision made for post node {post_node_id}: {decision_outcome.get('decision')}")

        # Distribution is triggered *within* make_decision if thresholds met

    except Exception as e:
        logger.error(f"Error during analysis pipeline for post node {post_node_id}: {e}", exc_info=True)
        # Optionally update post status in DB to indicate analysis failure via MCP?


# --- Lifespan Management ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    global mcp_session, llm_interface, report_generator, fact_checker, \
           contradiction_detector, evasion_detector, disinformation_analyzer, decision_engine
    logger.info("A2A Host application startup...")
    try:
        # Initialize MCP Session
        mcp_session = requests.Session()
        if INTERNAL_SERVICE_API_KEY:
            mcp_session.headers.update({"X-API-KEY": INTERNAL_SERVICE_API_KEY, "Accept": "application/json"})
            logger.info("A2A Host: MCP client session initialized with API Key.")
        else:
            logger.warning("A2A Host: Running without internal API key. MCP calls might fail auth.")

        # Initialize LLM Interface (reads keys from config)
        llm_interface = LLMInterface()

        # Initialize analysis engines (passing LLM interface and MCP client/session)
        # Note: MCP interaction for context fetching is now within the analysis modules themselves using call_mcp_api helper
        fact_checker = FactChecker(llm_interface=llm_interface)
        contradiction_detector = ContradictionDetector(llm_interface=llm_interface)
        evasion_detector = EvasionDetector(llm_interface=llm_interface)
        disinformation_analyzer = DisinformationAnalyzer(llm_interface=llm_interface)
        # Decision engine needs MCP client (via session) to update scores
        decision_engine = DecisionEngine() # It uses the global mcp_session via call_mcp_api now
        report_generator = ReportGenerator() # It uses the global mcp_session via call_mcp_api now

        logger.info("LLM Interface and analysis engines initialized.")

    except Exception as e:
        logger.critical(f"CRITICAL ERROR during A2A Host startup: {e}", exc_info=True)
        raise RuntimeError("Failed to initialize critical A2A Host components") from e
    yield
    # Shutdown
    logger.info("A2A Host application shutdown...")
    if mcp_session:
        mcp_session.close()
        logger.info("MCP session closed.")
    # Add any other cleanup needed
    logger.info("A2A Host resources cleaned up.")

# --- FastAPI App Creation ---
app = FastAPI(
    title="Oppo A2A Host",
    description="Provides opposition research data and analysis via A2A protocols, including real-time social media ingestion and LLM analysis.",
    version="0.1.0",
    lifespan=lifespan # Register lifespan context manager
)

# --- CORS Middleware ---
# Allow specific origins in production
origins = [
    "http://localhost",
    "http://localhost:8080", # Example frontend
    # Add allowed campaign website domains here if UI access needed
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins, # Or ["*"] for development
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- API Routers ---
# Token endpoint for user login
@app.post("/token", response_model=Token, tags=["Authentication"])
async def login_for_access_token_route(form_data: OAuth2PasswordRequestForm = Depends()):
    user = authenticate_user(form_data.username, form_data.password)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect username or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    access_token = create_access_token(data={"sub": user.username})
    return {"access_token": access_token, "token_type": "bearer"}

# Main API router for external A2A agents
app.include_router(main_api_router)


# --- Internal Ingestion Endpoint ---
# Secured with internal API key
@app.post(
    "/ingest/social_post",
    tags=["Internal Ingestion"],
    summary="Endpoint for listeners to submit new social posts",
    dependencies=[Depends(verify_internal_api_key)] # Secure this endpoint!
)
async def ingest_social_post_route(
    background_tasks: BackgroundTasks,
    post_payload: Dict[str, Any] = Body(...) # Receive raw dict from listener
    ):
    """
    Receives social post data from internal listeners, requests storage via MCP,
    and triggers the analysis pipeline as a background task.
    """
    global mcp_session # Use the global session for MCP calls

    # Basic validation of payload structure before processing
    if not post_payload or not isinstance(post_payload, dict) or not post_payload.get('candidate_id') or not post_payload.get('post_id'):
         logger.error(f"Received invalid ingestion payload: {str(post_payload)[:500]}")
         raise HTTPException(status_code=422, detail="Invalid post data format received.")

    logger.info(f"Received ingestion request: Platform={post_payload.get('source_platform')}, ID={post_payload.get('post_id')}, Cand={post_payload.get('candidate_id')}")

    # 1. Request MCP Server to store the post
    mcp_response = await call_mcp_api('POST', '/social_post', json_payload=post_payload)

    if not mcp_response or mcp_response.get('error'):
        error_detail = mcp_response.get('error', 'Unknown error storing post via MCP') if mcp_response else 'No response from MCP'
        logger.error(f"Failed to store social post via MCP: {error_detail}")
        # Decide if we should still trigger analysis? Probably not if storage failed.
        raise HTTPException(status_code=502, detail=f"Failed to store social post: {error_detail}") # Bad Gateway

    post_node_id = mcp_response.get('post_node_id')
    if not post_node_id:
        logger.error(f"MCP Server stored post but did not return node ID. Payload: {post_payload}")
        # Cannot trigger analysis without node ID
        raise HTTPException(status_code=500, detail="Internal error: Failed to get post node ID after storage.")

    logger.info(f"Post stored via MCP, node ID: {post_node_id}. Triggering background analysis.")

    # 2. Trigger Analysis Pipeline as Background Task
    background_tasks.add_task(run_analysis_pipeline, post_node_id, post_payload)

    return {"message": "Social post ingested and analysis triggered successfully", "post_node_id": post_node_id}


# --- Root Endpoint ---
@app.get("/", tags=["Root"], summary="Root endpoint for API status")
async def root():
    """Provides basic status information about the A2A Host."""
    return {"message": "Oppo A2A Host v0.1 (LLM-Powered) - Ready"}

# --- Health Check Endpoint ---
@app.get("/health", tags=["Health Check"], summary="Check service health")
async def health_check():
    """Performs basic health checks on the service and dependencies."""
    # Check MCP connection (simple GET request to MCP root)
    mcp_status = "unknown"
    if mcp_session and MCP_SERVER_URL:
        try:
            response = await asyncio.get_running_loop().run_in_executor(
                None,
                lambda: mcp_session.get(MCP_SERVER_URL, timeout=5)
            )
            if response.status_code == 200:
                mcp_status = "ok"
            else:
                mcp_status = f"error: MCP status {response.status_code}"
        except Exception as e:
            mcp_status = f"error: {str(e)[:100]}"
    else:
        mcp_status = "not configured"

    # Check if LLM interface seems configured
    llm_status = "ok" if llm_interface and llm_interface.providers else "not configured"

    # Determine overall status
    overall_ok = mcp_status == "ok" and llm_status == "ok"

    return {
        "status": "ok" if overall_ok else "error",
        "version": "0.1.0-llm",
        "dependencies": {
            "mcp_server": mcp_status,
            "llm_interface": llm_status,
        },
        "analysis_components_loaded": {
            "llm_interface": bool(llm_interface),
            "fact_checker": bool(fact_checker),
            "contradiction_detector": bool(contradiction_detector),
            "evasion_detector": bool(evasion_detector),
            "disinformation_analyzer": bool(disinformation_analyzer),
            "decision_engine": bool(decision_engine),
            "report_generator": bool(report_generator)
        }
    }


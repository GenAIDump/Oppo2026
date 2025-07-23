# File: Oppo/analysis/report_generator.py
# Purpose: Generates comprehensive reports based on data fetched via MCP Server

import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
import requests
import os

# Import necessary components
# Use models for structure hinting - assuming they are in database package
try:
    from database import Candidate, Statement, Vote, SocialPost
except ImportError:
    logging.error("Could not import data models for ReportGenerator.")
    # Define dummy classes if needed, or ensure PYTHONPATH is correct
    class Candidate: pass
    class Statement: pass
    class Vote: pass
    class SocialPost: pass

# Use config to get MCP server URL and API key
try:
    from a2a_host.config import MCP_SERVER_URL, INTERNAL_SERVICE_API_KEY
except ImportError:
    # Fallback for standalone use or different structure
    logger = logging.getLogger(__name__) # Need logger instance here
    logger.warning("Could not import config from a2a_host. Attempting to load MCP_SERVER_URL/INTERNAL_SERVICE_API_KEY from environment.")
    MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://localhost:8001")
    INTERNAL_SERVICE_API_KEY = os.getenv("INTERNAL_SERVICE_API_KEY")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Constants for report generation
RECENT_POST_LIMIT = 20
CONTEXT_STATEMENT_LIMIT = 10
CONTEXT_VOTE_LIMIT = 10
SIGNIFICANCE_THRESHOLD_REPORT = 0.6 # Example threshold for highlighting in report
DISINFO_THRESHOLD_REPORT = 0.7 # Example threshold

class ReportGenerator:
    """
    Generates opposition research reports by fetching and compiling analyzed data
    from the Modern Context Protocol (MCP) Server.
    """
    def __init__(self, mcp_base_url: str = MCP_SERVER_URL, api_key: Optional[str] = INTERNAL_SERVICE_API_KEY):
        """
        Initializes the ReportGenerator.
        Args:
            mcp_base_url: The base URL of the MCP Server.
            api_key: The internal API key for authenticating with the MCP Server.
        """
        self.mcp_base_url = mcp_base_url
        self.api_key = api_key
        self.session = requests.Session()
        if self.api_key:
            self.session.headers.update({"X-API-KEY": self.api_key})
            logger.info("ReportGenerator initialized with API Key.")
        else:
            logger.warning("ReportGenerator initialized without INTERNAL_SERVICE_API_KEY. MCP requests may fail.")
        self.session.headers.update({"Accept": "application/json"})
        logger.info(f"ReportGenerator initialized, targeting MCP at {self.mcp_base_url}")

    def _fetch_from_mcp(self, endpoint: str, params: Optional[Dict] = None) -> Optional[Any]:
        """Helper function to fetch data from the MCP server with error handling."""
        url = f"{self.mcp_base_url.rstrip('/')}/{endpoint.lstrip('/')}"
        params = params or {}
        logger.debug(f"MCP Request: GET {url} PARAMS: {params}")
        try:
            response = self.session.get(url, params=params, timeout=30) # Increased timeout
            response.raise_for_status() # Raise HTTPError for 4xx/5xx responses
            data = response.json()
            # Assuming MCP server returns a standard format like {'status': 'success', 'data': ...}
            # Adjust based on actual MCP response structure
            if isinstance(data, dict) and data.get("status") == "success":
                logger.debug(f"MCP Response Success for {endpoint}")
                # Return the actual data payload based on expected structure from MCP endpoints
                # This might be data['candidate'], data['posts'], data['statements'] etc.
                # Returning the whole dict for flexibility for now, parsing happens in caller.
                return data
            elif isinstance(data, dict):
                 error_msg = data.get('message', data.get('detail', 'Unknown MCP error structure'))
                 logger.error(f"MCP Error fetching {endpoint}: {error_msg}")
                 return {"error": error_msg} # Return error structure
            else:
                # Handle cases where response is not a dict or missing status
                 logger.error(f"Unexpected MCP response format from {endpoint}: {str(data)[:200]}")
                 return {"error": "Unexpected MCP response format"}

        except requests.exceptions.Timeout:
             logger.error(f"Timeout fetching from MCP endpoint: {endpoint}")
             return {"error": "Timeout"}
        except requests.exceptions.HTTPError as e:
             logger.error(f"HTTP Error fetching from MCP endpoint {endpoint}: {e.response.status_code} {e.response.text[:200]}")
             # Pass detail if available
             error_detail = f"HTTP Error {e.response.status_code}"
             try:
                  err_json = e.response.json()
                  error_detail = err_json.get('detail', error_detail)
             except ValueError:
                  pass # Ignore if response is not JSON
             return {"error": error_detail}
        except requests.exceptions.RequestException as e:
            logger.error(f"Network Error fetching from MCP endpoint {endpoint}: {e}", exc_info=False)
            return {"error": "Network Error"}
        except Exception as e:
             logger.error(f"Unexpected error processing MCP response from {endpoint}: {e}", exc_info=True)
             return {"error": "Unexpected Processing Error"}


    def _format_post_for_report(self, post_data: dict) -> dict:
         """Selects and formats key fields from a SocialPost for the report."""
         return {
              "platform": post_data.get("source_platform"),
              "content_snippet": (post_data.get("content", "") or "")[:300] + ("..." if len(post_data.get("content", "")) > 300 else ""),
              "timestamp_utc": post_data.get("timestamp"), # Already ISO string from model likely
              "url": post_data.get("url"),
              "author": post_data.get("author_username"),
              "significance_score": round(post_data.get("significance_score", 0.0), 3),
              "disinfo_score": round(post_data.get("disinfo_score", 0.0), 3),
              "analysis_flags": post_data.get("analysis_flags", []),
         }

    def generate_report(self, candidate_id: str, topic_of_interest: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Generates a comprehensive opposition research report for a candidate by querying the MCP Server.

        Args:
            candidate_id: The stable unique identifier of the target candidate.
            topic_of_interest: Optional keyword/topic to filter context data.

        Returns:
            A dictionary containing the structured analysis report, or None on failure.
        """
        start_time = datetime.now(timezone.utc)
        logger.info(f"Generating report via MCP for candidate_id '{candidate_id}', topic: {topic_of_interest}")

        report: Dict[str, Any] = {
            "report_metadata": {
                "candidate_id": candidate_id,
                "topic_focus": topic_of_interest,
                "generated_at": start_time.isoformat(),
                "version": "Oppo-v0.1-MCP"
            },
            "candidate_profile": None,
            "summary": {
                "key_findings": [],
                "total_social_posts_analyzed": 0, # Might need separate MCP call for total count
                "recent_posts_included": 0,
                "significant_posts_found": 0, # Count based on fetched recent posts meeting threshold
                "disinfo_flags_found": 0, # Count based on fetched recent posts meeting threshold
                "contradiction_flags_found": 0 # Count based on fetched recent posts meeting threshold
            },
            "recent_activity": [], # Include recent posts formatted for report
            "historical_context": {
                "statements": [], # Key historical statements, topic-filtered if requested
                "votes": [], # Key votes, topic-filtered if requested
            },
            # Add other sections as needed (e.g., Donors, Full Contradiction List) fetched via MCP
            "error_log": []
        }

        # 1. Fetch Candidate Profile from MCP
        logger.debug(f"Fetching candidate profile for {candidate_id} via MCP")
        profile_response = self._fetch_from_mcp(f"/candidate/{candidate_id}")
        if not profile_response or profile_response.get('error') or not profile_response.get('candidate'):
            error_msg = profile_response.get('error', 'Failed to fetch candidate profile') if profile_response else 'No response from MCP'
            report["error_log"].append(error_msg)
            logger.error(f"Report generation failed: Could not retrieve profile for candidate {candidate_id}. Error: {error_msg}")
            return None # Profile is essential
        report["candidate_profile"] = profile_response['candidate']
        candidate_name = report["candidate_profile"].get("name", candidate_id)

        # 2. Fetch Recent Analyzed Social Posts from MCP
        logger.debug(f"Fetching recent analyzed social posts for {candidate_name} via MCP")
        # Assuming MCP has an endpoint like /social_posts/candidate/{candidate_id}
        post_params = {'limit': RECENT_POST_LIMIT, 'sort': 'timestamp_desc', 'include_analysis': 'true'}
        posts_response = self._fetch_from_mcp(f"/social_posts/candidate/{candidate_id}", params=post_params) # Endpoint needs implementation in MCP

        significant_count = 0
        disinfo_count = 0
        contradiction_count = 0
        formatted_posts = []

        if posts_response and not posts_response.get('error') and isinstance(posts_response.get('posts'), list):
             raw_posts = posts_response.get('posts', [])
             report["summary"]["recent_posts_included"] = len(raw_posts)
             # Assume total count might be in response or needs another query
             report["summary"]["total_social_posts_analyzed"] = posts_response.get('total_count', len(raw_posts))

             for post in raw_posts:
                 formatted_posts.append(self._format_post_for_report(post))
                 if post.get('significance_score', 0) >= SIGNIFICANCE_THRESHOLD_REPORT:
                      significant_count += 1
                 if post.get('disinfo_score', 0) >= DISINFO_THRESHOLD_REPORT:
                      disinfo_count += 1
                 if "CONTRADICTION" in str(post.get('analysis_flags', [])).upper(): # Simple check
                      contradiction_count += 1
        elif posts_response and posts_response.get('error'):
             report["error_log"].append(f"Error fetching social posts: {posts_response.get('error')}")
             logger.warning(f"Could not fetch recent social posts for {candidate_name}: {posts_response.get('error')}")
        else:
             logger.info(f"No recent social posts found via MCP for {candidate_name}.")

        report["recent_activity"] = formatted_posts
        report["summary"]["significant_posts_found"] = significant_count
        report["summary"]["disinfo_flags_found"] = disinfo_count
        report["summary"]["contradiction_flags_found"] = contradiction_count

        # 3. Fetch Historical Context (Statements / Votes) from MCP
        logger.debug(f"Fetching historical context for {candidate_name}, topic: {topic_of_interest} via MCP")
        context_params = {'limit': CONTEXT_STATEMENT_LIMIT}
        if topic_of_interest:
            context_params['topic'] = topic_of_interest

        statements_response = self._fetch_from_mcp(f"/context/statements/{candidate_id}", params=context_params)
        if statements_response and not statements_response.get('error'):
            report["historical_context"]["statements"] = statements_response.get('statements', [])
        elif statements_response and statements_response.get('error'):
             report["error_log"].append(f"Error fetching statements: {statements_response.get('error')}")

        context_params['limit'] = CONTEXT_VOTE_LIMIT # Reset limit for votes
        votes_response = self._fetch_from_mcp(f"/context/votes/{candidate_id}", params=context_params)
        if votes_response and not votes_response.get('error'):
             report["historical_context"]["votes"] = votes_response.get('votes', [])
        elif votes_response and votes_response.get('error'):
             report["error_log"].append(f"Error fetching votes: {votes_response.get('error')}")


        # 4. Generate Summary Key Findings
        key_findings = []
        if report["summary"]["significant_posts_found"] > 0:
            key_findings.append(f"Identified {report['summary']['significant_posts_found']} recent social media post(s) scored above significance threshold ({SIGNIFICANCE_THRESHOLD_REPORT}).")
        if report["summary"]["disinfo_flags_found"] > 0:
            key_findings.append(f"Flagged {report['summary']['disinfo_flags_found']} recent social media post(s) scored above disinformation threshold ({DISINFO_THRESHOLD_REPORT}).")
        if report["summary"]["contradiction_flags_found"] > 0:
             key_findings.append(f"Found {report['summary']['contradiction_flags_found']} recent post(s) potentially contradicting historical record.")

        if not key_findings and report["summary"]["recent_posts_included"] > 0:
             key_findings.append("Analysis of recent social posts found no high-scoring significance, disinformation, or contradiction flags based on current thresholds.")
        elif not key_findings:
             key_findings.append("No recent social activity analyzed or no significant findings to report.")

        report["summary"]["key_findings"] = key_findings


        # 5. Finalize Report
        end_time = datetime.now(timezone.utc)
        duration = (end_time - start_time).total_seconds()
        report["report_metadata"]["duration_seconds"] = round(duration, 2)
        logger.info(f"Opposition report generation complete for '{candidate_name}'. Duration: {duration:.2f} seconds.")

        return report

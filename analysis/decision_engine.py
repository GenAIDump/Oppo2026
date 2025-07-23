# File: Oppo/analysis/decision_engine.py
# Purpose: Makes decisions based on combined (LLM-derived) analysis results.

import logging
import os
from typing import Dict, Any, List, Optional

# Use config from a2a_host package
try:
    from a2a_host.config import LOG_LEVEL
except ImportError:
     logging.basicConfig(level=logging.INFO)
     logger = logging.getLogger(__name__)
     logger.warning("Could not import config from a2a_host for DecisionEngine.")
     LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

# Import distribution trigger function
try:
     from a2a_host.a2a_protocol import trigger_distribution
except ImportError:
     logger.error("Could not import trigger_distribution from a2a_host. A2A distribution disabled.")
     def trigger_distribution(*args, **kwargs): # Dummy function
          logger.warning("A2A distribution trigger called but is not available.")
          pass

# Import MCP client helper (or directly use requests if preferred)
# This engine needs to send updates to the MCP Server
import requests
try:
    from a2a_host.config import MCP_SERVER_URL, INTERNAL_SERVICE_API_KEY
except ImportError:
     MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://localhost:8001")
     INTERNAL_SERVICE_API_KEY = os.getenv("INTERNAL_SERVICE_API_KEY")


# Configure logging
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format='%(asctime)s:%(levelname)s:%(name)s:%(message)s'
)
logger = logging.getLogger(__name__)


class DecisionEngine:
    """
    Combines results from various analysis modules (LLM-powered)
    to determine post significance, flag potential disinformation,
    and trigger distribution or storage updates via MCP Server.
    """
    def __init__(self,
                 significance_threshold: float = 0.7,
                 disinfo_alert_threshold: float = 0.8,
                 contradiction_weight: float = 0.4,
                 evasion_weight: float = 0.1,
                 fact_check_false_weight: float = 0.5, # Higher weight for confirmed false
                 disinfo_score_weight: float = 0.3 # Weight of explicit disinfo score
                 ):
        """
        Initializes the Decision Engine with thresholds and weights.
        """
        self.significance_threshold = significance_threshold
        self.disinfo_alert_threshold = disinfo_alert_threshold
        # Weights for calculating significance score (total should ideally be around 1.0, but can be adjusted)
        self.weights = {
            'contradiction': contradiction_weight,
            'evasion': evasion_weight,
            'fact_check_false': fact_check_false_weight,
            'disinfo_score': disinfo_score_weight,
            # Add weights for other factors if needed (e.g., sentiment, specific flags)
        }
        self.session = requests.Session() # For MCP calls
        if INTERNAL_SERVICE_API_KEY:
            self.session.headers.update({"X-API-KEY": INTERNAL_SERVICE_API_KEY, "Accept": "application/json"})
        else:
            logger.warning("DecisionEngine running without internal API key. MCP calls might fail auth.")

        logger.info(f"DecisionEngine initialized. Sig Threshold: {self.significance_threshold}, Disinfo Alert Threshold: {self.disinfo_alert_threshold}, Weights: {self.weights}")


    def _update_post_analysis_mcp(self, post_node_id: str, analysis_payload: dict) -> bool:
         """Sends analysis results update to MCP Server."""
         if not MCP_SERVER_URL:
              logger.error("Cannot update post analysis: MCP_SERVER_URL not configured.")
              return False
         if not post_node_id:
              logger.error("Cannot update post analysis: post_node_id is missing.")
              return False

         url = f"{MCP_SERVER_URL.rstrip('/')}/social_post/{post_node_id}/analysis"
         logger.debug(f"Attempting to update post analysis via MCP: PUT {url} Payload: {analysis_payload}")
         try:
              response = self.session.put(url, json=analysis_payload, timeout=15)
              response.raise_for_status()
              data = response.json()
              if data.get("status") == "success":
                   logger.info(f"Successfully updated analysis via MCP for post node: {post_node_id}")
                   return True
              else:
                   logger.error(f"MCP Error updating analysis for {post_node_id}: {data.get('message', data.get('detail', 'Unknown error'))}")
                   return False
         except requests.exceptions.RequestException as e:
              logger.error(f"Failed to update analysis via MCP for {post_node_id}: {e}", exc_info=False)
              if e.response is not None:
                  logger.error(f"MCP Update Analysis Response: {e.response.status_code} {e.response.text[:200]}")
              return False
         except Exception as e:
              logger.error(f"Unexpected error updating analysis via MCP for {post_node_id}: {e}", exc_info=True)
              return False


    def make_decision(self, post_node_id: str, post_data: dict, analysis_results: Dict[str, Any]) -> Dict[str, Any]:
        """
        Combines LLM-derived analysis results to make a decision and update storage.

        Args:
            post_node_id (str): The Neo4j element ID of the SocialPost node.
            post_data (dict): The original ingested post data (for context in distribution).
            analysis_results (dict): Aggregated results from ALL analysis modules.
                Example: {
                    'contradiction': {'contradiction_score': 0.8, 'conflicts': [...]},
                    'evasion': {'evasion_score': 0.6, 'evasion_flags': [...]},
                    'fact_check': {'fact_check_rating': 'Verified - False', 'fact_check_evidence': [...]},
                    'disinformation': {'disinfo_score': 0.7, 'matched_narratives': [...], 'disinfo_flags': [...]}
                }

        Returns:
            dict: Decision outcome, e.g.,
                  {'decision': 'DISTRIBUTE_ALERT',
                   'final_significance_score': 0.85,
                   'final_disinfo_score': 0.7,
                   'reason_flags': ['HIGH_CONTRADICTION', 'HIGH_DISINFO']}
        """
        if not post_node_id:
            logger.error("DecisionEngine received invalid post_node_id. Cannot proceed.")
            return {"decision": "ERROR", "reason_flags": ["INVALID_INPUT"]}

        logger.info(f"Making decision for post node {post_node_id}.")
        logger.debug(f"Received analysis results: {analysis_results}")

        # --- Extract Scores and Flags from LLM Analysis Results ---
        contradiction_score = analysis_results.get('contradiction', {}).get('contradiction_score', 0.0)
        evasion_score = analysis_results.get('evasion', {}).get('evasion_score', 0.0)
        fact_check_rating = analysis_results.get('fact_check', {}).get('fact_check_rating', 'Not Found / Unverifiable')
        disinfo_score = analysis_results.get('disinformation', {}).get('disinfo_score', 0.0)
        disinfo_flags = analysis_results.get('disinformation', {}).get('disinfo_flags', [])

        # --- Calculate Significance Score (Example Logic) ---
        # This needs refinement based on desired priorities.
        significance_score = 0.0
        reason_flags = []

        # Contribution from contradiction
        if contradiction_score > 0.5:
             significance_score += contradiction_score * self.weights['contradiction']
             reason_flags.append(f"CONTRADICTION_SCORE_{contradiction_score:.2f}")

        # Contribution from evasion
        if evasion_score > 0.5:
             significance_score += evasion_score * self.weights['evasion']
             reason_flags.append(f"EVASION_SCORE_{evasion_score:.2f}")

        # Contribution from fact-checking
        if fact_check_rating == "Verified - False":
             significance_score += 1.0 * self.weights['fact_check_false'] # High impact
             reason_flags.append("FACT_CHECK_FALSE")
        elif fact_check_rating == "Verified - Mixed":
             significance_score += 0.5 * self.weights['fact_check_false'] # Medium impact
             reason_flags.append("FACT_CHECK_MIXED")

        # Contribution from disinformation analysis score
        if disinfo_score > 0.3: # Add contribution even for medium disinfo score
             significance_score += disinfo_score * self.weights['disinfo_score']
        # Add specific disinfo flags to overall flags
        reason_flags.extend(disinfo_flags)

        # Normalize significance score
        final_significance_score = min(1.0, max(0.0, significance_score))
        final_disinfo_score = min(1.0, max(0.0, disinfo_score)) # Ensure disinfo score is also clamped

        # --- Make Decision based on thresholds ---
        decision = 'IGNORE'
        distribute = False

        # Significance Check
        if final_significance_score >= self.significance_threshold:
            decision = 'STORE_SIGNIFICANT'
            reason_flags.append(f"SIGNIFICANT_SCORE_{final_significance_score:.2f}")
            distribute = True # Distribute significant items

        # Disinformation Check
        if final_disinfo_score >= self.disinfo_alert_threshold:
            decision = 'FLAG_DISINFO' # Overrides 'significant' if both high
            reason_flags.append(f"HIGH_DISINFO_SCORE_{final_disinfo_score:.2f}")
            distribute = True # Definitely distribute high disinfo items

        if distribute:
            decision = 'DISTRIBUTE_ALERT' # Final decision state if distribution triggered

        # --- Update Neo4j via MCP Server ---
        analysis_update_payload = {
            "significance_score": final_significance_score,
            "disinfo_score": final_disinfo_score,
            "analysis_flags": sorted(list(set(reason_flags))) # Unique sorted flags
        }
        update_success = self._update_post_analysis_mcp(post_node_id, analysis_update_payload)
        if not update_success:
            # Log error but continue with distribution if needed? Or halt?
            logger.error(f"Failed to update analysis scores in DB for post {post_node_id}. Distribution might proceed with stale DB data.")
            # Decide if decision should change on DB update failure
            # decision = "ERROR_DB_UPDATE"

        # --- Trigger Distribution (via A2A Host's protocol handler) ---
        if distribute:
            logger.info(f"Triggering A2A distribution for post {post_node_id}")
            # Ensure post_data includes necessary info for the alert payload
            trigger_distribution(
                post_id=post_node_id, # Pass internal ID for reference
                significance_score=final_significance_score,
                disinfo_score=final_disinfo_score,
                reason=" | ".join(sorted(list(set(reason_flags)))), # Combine flags for reason string
                post_data=post_data # Pass original post data for context
            )

        final_outcome = {
            'decision': decision,
            'final_significance_score': final_significance_score,
            'final_disinfo_score': final_disinfo_score,
            'reason_flags': sorted(list(set(reason_flags)))
        }
        logger.info(f"Decision for post {post_node_id}: {final_outcome}")
        return final_outcome

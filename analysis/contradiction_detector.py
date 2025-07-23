# File: Oppo/analysis/contradiction_detector.py
# Purpose: Uses LLM to detect contradictions between a new post and historical context.

import logging
import os
import json
import asyncio
from typing import Dict, List, Any, Optional, Tuple

# Import LLM Interface and provider type
from .llm_interface import LLMInterface, LlmProvider
# Import data models for type hinting
try:
    from database.data_models import Statement, Vote, SocialPost
    MODELS_LOADED = True
except ImportError:
     # Ensure logger is available if config import failed
     log_level_env = os.getenv("LOG_LEVEL", "INFO").upper()
     logging.basicConfig(level=getattr(logging, log_level_env, logging.INFO), format='%(asctime)s:%(levelname)s:%(name)s:%(lineno)d:%(message)s')
     logger = logging.getLogger(__name__)
     logger.error("Could not import data models for ContradictionDetector.")
     MODELS_LOADED = False
     # Define dummy classes or skip type hinting
     class Statement: pass
     class Vote: pass
     class SocialPost: pass

# Import config for LLM provider selection
try:
    from a2a_host.config import CONTRADICTION_LLM_PROVIDER, LOG_LEVEL
    CONFIG_LOADED = True
except ImportError:
     # Fallback logging setup
     log_level_env = os.getenv("LOG_LEVEL", "INFO").upper()
     logging.basicConfig(level=getattr(logging, log_level_env, logging.INFO), format='%(asctime)s:%(levelname)s:%(name)s:%(lineno)d:%(message)s')
     logger = logging.getLogger(__name__)
     logger.warning("Could not import config from a2a_host for ContradictionDetector. Using environment variables.")
     CONTRADICTION_LLM_PROVIDER = os.getenv("CONTRADICTION_LLM_PROVIDER", "GEMINI") # Default to Gemini
     LOG_LEVEL = log_level_env
     CONFIG_LOADED = True

# Ensure logging is configured
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format='%(asctime)s:%(levelname)s:%(name)s:%(lineno)d:%(message)s',
    force=True # Reconfigure if needed
)
logger = logging.getLogger(__name__)

# --- Constants ---
DEFAULT_PROVIDER: LlmProvider = CONTRADICTION_LLM_PROVIDER or "GEMINI" # Fallback provider

# --- Prompts (Customize these extensively) ---
# This prompt aims for a structured JSON output. Fine-tuning or more examples might improve reliability.
CONTRADICTION_SYSTEM_PROMPT = """
You are an expert political analyst specializing in identifying contradictions in statements and actions.
Analyze the provided 'New Statement/Post' in the context of the 'Historical Statements' and 'Voting Record'.
Determine if the new statement CONTRADICTS any specific historical statement or vote.
Focus on direct contradictions or significant shifts in position on the SAME core topic. Ignore unrelated topics or minor wording differences unless they represent a substantive change.
Provide your analysis STRICTLY in JSON format with the following keys:
- "contradiction_found": boolean (true if a clear contradiction is found, false otherwise)
- "contradiction_score": float (Your confidence level [0.0 to 1.0] that a contradiction exists. Assign 0.0 if contradiction_found is false.)
- "explanation": string (A concise explanation justifying your finding. If a contradiction exists, cite the conflicting item ID and explain the conflict. If no contradiction, state why.)
- "conflicting_item_type": string | null (Type of conflicting item: 'statement' or 'vote'. Null if no conflict.)
- "conflicting_item_id": string | null (ID of the conflicting statement or vote from the context provided. Null if no conflict.)
"""

CONTRADICTION_USER_PROMPT_TEMPLATE = """
**Candidate Context:** (All statements/votes are from the same candidate)

**New Statement/Post:**
{new_post}

**Historical Context:**

*Recent Statements (Limit {max_statements}):*
{statements_context}

*Recent Voting Record (Limit {max_votes}):*
{votes_context}

**Analysis Task:** Based ONLY on the provided information, does the 'New Statement/Post' contradict any specific historical statement or vote on the same core topic? Output ONLY the JSON object as specified in the system prompt.
"""


class ContradictionDetector:
    """
    Uses an LLM via the LLMInterface to detect contradictions between
    a new post and historical context (statements, votes) fetched via MCP.
    """
    def __init__(self, llm_interface: LLMInterface):
        """
        Initializes the ContradictionDetector.
        Args:
            llm_interface: An instance of the LLMInterface.
        """
        if not isinstance(llm_interface, LLMInterface):
             raise TypeError("llm_interface must be an instance of LLMInterface")
        self.llm = llm_interface
        # Determine the provider from config, default if not set or invalid
        self.provider: LlmProvider = DEFAULT_PROVIDER
        if CONTRADICTION_LLM_PROVIDER not in self.llm.providers:
             logger.warning(f"Configured contradiction provider '{CONTRADICTION_LLM_PROVIDER}' not available. Falling back.")
             # Fallback logic: try configured default, then first available
             available_providers = list(self.llm.providers.keys())
             if DEFAULT_PROVIDER in available_providers:
                  self.provider = DEFAULT_PROVIDER
             elif available_providers:
                  self.provider = available_providers[0]
             else:
                  logger.error("No LLM providers available for ContradictionDetector!")
                  # Raise error or allow to proceed with provider=None?
                  raise RuntimeError("No configured LLM provider available for contradiction detection.")

        logger.info(f"ContradictionDetector initialized using LLM provider: {self.provider}")

    def _format_context(self, items: List[Any], item_type: str, max_items: int) -> str:
        """Formats historical statements or votes for the prompt."""
        if not items:
            return f"No recent {item_type} provided for comparison."

        formatted = []
        for i, item_dict in enumerate(items[:max_items]):
            # Handle items being dictionaries fetched from MCP
            if not isinstance(item_dict, dict): continue

            item_id = item_dict.get('statement_id', item_dict.get('vote_id', f"item_{i+1}")) # Use available ID
            date_info = item_dict.get('date', item_dict.get('vote_date'))
            date_str = date_info if isinstance(date_info, str) else "Unknown Date" # Assume date is already string from MCP/model
            # Try parsing just in case for formatting, but default to string
            try:
                 parsed_date = datetime.fromisoformat(date_str.replace('Z', '+00:00')).date()
                 date_str = parsed_date.strftime('%Y-%m-%d')
            except: pass # Keep original string if parsing fails

            if item_type == "statements":
                text = item_dict.get('text', '')[:250] + "..." # Slightly longer snippet
                formatted.append(f"- ID: {item_id} ({date_str}): {text}")
            elif item_type == "votes":
                desc = item_dict.get('vote_question', item_dict.get('bill_title', 'N/A'))[:200] # Vote description/title snippet
                position = item_dict.get('position', '?')
                formatted.append(f"- ID: {item_id} ({date_str}): Position={position}, Desc='{desc}...'")

        return "\n".join(formatted) if formatted else f"No relevant {item_type} found or provided."


    async def analyze_new_post_contradictions_llm(
        self,
        candidate_id: str, # Used for logging/context, not directly in prompt unless needed
        new_post_content: str,
        historical_statements: List[Dict], # Expect dicts from MCP
        historical_votes: List[Dict],      # Expect dicts from MCP
        max_context_statements: int = 7,   # Increase context slightly
        max_context_votes: int = 15
    ) -> Dict[str, Any]:
        """
        Analyzes a new post for contradictions against historical data using an LLM.

        Args:
            candidate_id: The candidate's identifier (for logging).
            new_post_content: The text content of the new post.
            historical_statements: List of historical statement dicts from MCP.
            historical_votes: List of historical vote dicts from MCP.
            max_context_statements: Max historical statements to include in prompt.
            max_context_votes: Max historical votes to include in prompt.

        Returns:
            A dictionary with analysis results:
            {'contradiction_score': float, 'explanation': str, 'conflicting_item_type': str|None, 'conflicting_item_id': str|None, 'error': str|None}
        """
        logger.info(f"Running LLM contradiction check for candidate {candidate_id}, post: '{new_post_content[:50]}...'")
        default_response = {'contradiction_score': 0.0, 'explanation': 'Analysis could not be performed.', 'conflicting_item_type': None, 'conflicting_item_id': None, 'error': 'LLM analysis skipped or failed.'}

        if not new_post_content:
            logger.warning("Cannot check contradiction: New post content is empty.")
            default_response['explanation'] = "No content provided in the new post."
            default_response['error'] = "Missing content"
            return default_response

        if not self.llm or not self.provider:
             logger.error("LLM Interface or provider not available for contradiction check.")
             return default_response

        # Format context for the prompt
        statements_context_str = self._format_context(historical_statements, "statements", max_context_statements)
        votes_context_str = self._format_context(historical_votes, "votes", max_context_votes)

        # Construct the full prompt
        prompt = CONTRADICTION_USER_PROMPT_TEMPLATE.format(
            new_post=new_post_content,
            max_statements=max_context_statements,
            statements_context=statements_context_str,
            max_votes=max_context_votes,
            votes_context=votes_context_str
        )

        # Add system prompt if provider supports it (e.g., Anthropic)
        llm_kwargs = {}
        if self.provider == "ANTHROPIC":
             llm_kwargs["system_prompt"] = CONTRADICTION_SYSTEM_PROMPT

        # Call the LLM via the interface, requesting JSON output
        llm_response = await self.llm.call_llm_async(
            prompt=prompt if self.provider != "ANTHROPIC" else CONTRADICTION_USER_PROMPT_TEMPLATE, # Pass system prompt separately for Anthropic
            provider=self.provider,
            json_output=True, # Request JSON
            **llm_kwargs
        )

        # Parse the LLM response
        if llm_response['status'] == 'success' and isinstance(llm_response['result'], dict):
            result_json = llm_response['result']
            logger.debug(f"LLM Contradiction JSON result: {result_json}")
            # Validate expected keys
            contradiction_found = result_json.get('contradiction_found', False)
            score = result_json.get('contradiction_score', 0.0 if not contradiction_found else 0.5) # Default score if boolean only
            explanation = result_json.get('explanation', 'No explanation provided.')
            item_type = result_json.get('conflicting_item_type')
            item_id = result_json.get('conflicting_item_id')

            # Basic type validation/conversion
            try:
                score = float(score)
                if not (0.0 <= score <= 1.0):
                     logger.warning(f"LLM returned out-of-range contradiction_score: {score}. Clamping.")
                     score = min(max(score, 0.0), 1.0) # Clamp score
            except (ValueError, TypeError):
                 logger.warning(f"LLM returned invalid contradiction_score: {score}. Defaulting based on contradiction_found flag.")
                 score = 0.75 if contradiction_found else 0.0 # Assign default confidence if score invalid

            return {
                'contradiction_score': round(score, 3),
                'explanation': explanation,
                'conflicting_item_type': item_type if isinstance(item_type, str) and item_type in ['statement', 'vote'] else None,
                'conflicting_item_id': str(item_id) if item_id else None,
                'error': None
            }
        elif llm_response['status'] == 'success' and isinstance(llm_response['result'], str):
             # Handle case where LLM failed to return valid JSON despite request
             logger.warning(f"LLM contradiction check returned string instead of JSON: {llm_response['result'][:200]}...")
             # Attempt a simple heuristic parse or return default error
             if "contradiction: true" in llm_response['result'].lower() or "contradiction_found\": true" in llm_response['result'].lower():
                  score = 0.75 # Assign arbitrary high score
                  explanation = "LLM indicated contradiction but failed JSON format."
                  return {'contradiction_score': score, 'explanation': explanation, 'conflicting_item_type': None, 'conflicting_item_id': None, 'error': "LLM JSON format error"}
             else:
                  return {'contradiction_score': 0.0, 'explanation': 'LLM analysis inconclusive (format error).', 'conflicting_item_type': None, 'conflicting_item_id': None, 'error': "LLM JSON format error"}
        else:
            # Handle API errors or blocked content
            logger.error(f"LLM contradiction check failed for candidate {candidate_id}. Error: {llm_response.get('error')}")
            default_response['error'] = llm_response.get('error', 'Unknown LLM API error')
            if llm_response.get('blocked'):
                 default_response['explanation'] = f"Analysis blocked by content safety filter: {llm_response.get('block_reason')}"
            return default_response


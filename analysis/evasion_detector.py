# File: Oppo/analysis/evasion_detector.py
# Purpose: Uses LLM to analyze text for evasiveness.

import logging
import os
import json
import asyncio
from typing import Dict, List, Any, Optional

# Import LLM Interface and provider type
from .llm_interface import LLMInterface, LlmProvider

# Import config for LLM provider selection
try:
    from a2a_host.config import EVASION_LLM_PROVIDER, LOG_LEVEL
    CONFIG_LOADED = True
except ImportError:
     # Fallback logging setup
     log_level_env = os.getenv("LOG_LEVEL", "INFO").upper()
     logging.basicConfig(level=getattr(logging, log_level_env, logging.INFO), format='%(asctime)s:%(levelname)s:%(name)s:%(lineno)d:%(message)s')
     logger = logging.getLogger(__name__)
     logger.warning("Could not import config from a2a_host for EvasionDetector. Using environment variables.")
     EVASION_LLM_PROVIDER = os.getenv("EVASION_LLM_PROVIDER", "GEMINI") # Default to Gemini
     LOG_LEVEL = log_level_env
     CONFIG_LOADED = True

# Ensure logging is configured
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format='%(asctime)s:%(levelname)s:%(name)s:%(lineno)d:%(message)s',
    force=True
)
logger = logging.getLogger(__name__)

# --- Constants ---
DEFAULT_PROVIDER: LlmProvider = EVASION_LLM_PROVIDER or "GEMINI" # Fallback provider

# --- Prompts (Customize these extensively) ---
EVASION_SYSTEM_PROMPT = """
You are an expert analyst skilled at detecting evasive language in political communication.
Analyze the provided 'Statement/Post' for linguistic patterns commonly associated with evasion, such as:
- Vagueness or ambiguity (using words like 'maybe', 'perhaps', 'some', 'certain things').
- Overly complex sentence structures that obscure meaning.
- Use of passive voice to avoid assigning responsibility.
- Responding to a question with another question or deflecting the topic.
- Excessive use of hedging language ("I think", "it seems", "potentially").
- Abrupt topic changes or non-answers.
- Lack of specific details or concrete examples when expected.

Provide your analysis in JSON format with the following keys:
- "evasion_detected": boolean (true if evasive patterns are detected, false otherwise)
- "evasion_score": float (estimated confidence level of evasion, 0.0 to 1.0. Higher means more likely evasive)
- "evasion_flags": list[string] (List of specific patterns identified, e.g., ["VAGUENESS", "TOPIC_DEFLECTION", "PASSIVE_VOICE", "HEDGING"]). If none, return empty list [].
- "explanation": string (Briefly justify the score and flags, citing examples from the text if possible.)
"""

EVASION_USER_PROMPT_TEMPLATE = """
**Statement/Post to Analyze:**
{text_content}

**Analysis Task:** Based ONLY on the provided text, analyze it for linguistic patterns indicating evasion, as described in the system prompt. Provide your analysis in the specified JSON format.
"""

class EvasionDetector:
    """Analyzes text for evasiveness using an LLM."""

    def __init__(self, llm_interface: LLMInterface):
        """
        Initializes the EvasionDetector.
        Args:
            llm_interface: An instance of the LLMInterface.
        """
        if not isinstance(llm_interface, LLMInterface):
             raise TypeError("llm_interface must be an instance of LLMInterface")
        self.llm = llm_interface
        # Determine the provider from config
        self.provider: LlmProvider = DEFAULT_PROVIDER
        if EVASION_LLM_PROVIDER not in self.llm.providers:
             logger.warning(f"Configured evasion provider '{EVASION_LLM_PROVIDER}' not available. Falling back.")
             available_providers = list(self.llm.providers.keys())
             if DEFAULT_PROVIDER in available_providers: self.provider = DEFAULT_PROVIDER
             elif available_providers: self.provider = available_providers[0]
             else: raise RuntimeError("No configured LLM provider available for evasion detection.")
        logger.info(f"EvasionDetector initialized using LLM provider: {self.provider}")

    async def analyze_evasiveness_llm(self, text_content: Optional[str]) -> Dict[str, Any]:
        """
        Analyzes text content for evasiveness using an LLM.

        Args:
            text_content: The text to analyze.

        Returns:
            Dict: {'evasion_score': float, 'evasion_flags': list, 'explanation': str, 'error': str|None}
        """
        default_response = {'evasion_score': 0.0, 'evasion_flags': [], 'explanation': 'Analysis could not be performed.', 'error': 'LLM analysis skipped or failed.'}

        if not text_content:
             logger.warning("Cannot analyze evasiveness: Input text is empty.")
             default_response['explanation'] = "No text content provided."
             default_response['error'] = "Missing content"
             return default_response

        if not self.llm or not self.provider:
             logger.error("LLM Interface or provider not available for evasion check.")
             return default_response

        logger.info(f"Running LLM evasion check for text: '{text_content[:100]}...'")

        # Construct the prompt
        prompt = EVASION_USER_PROMPT_TEMPLATE.format(text_content=text_content)

        llm_kwargs = {}
        if self.provider == "ANTHROPIC":
             llm_kwargs["system_prompt"] = EVASION_SYSTEM_PROMPT

        # Call the LLM via the interface, requesting JSON output
        llm_response = await self.llm.call_llm_async(
            prompt=prompt if self.provider != "ANTHROPIC" else EVASION_USER_PROMPT_TEMPLATE,
            provider=self.provider,
            json_output=True, # Request JSON
            **llm_kwargs
        )

        # Parse the LLM response
        if llm_response['status'] == 'success' and isinstance(llm_response['result'], dict):
            result_json = llm_response['result']
            logger.debug(f"LLM Evasion JSON result: {result_json}")
            # Validate expected keys and types
            evasion_detected = result_json.get('evasion_detected', False)
            score = result_json.get('evasion_score', 0.0 if not evasion_detected else 0.5) # Default score
            flags = result_json.get('evasion_flags', [])
            explanation = result_json.get('explanation', 'No explanation provided.')

            try:
                score = float(score)
                if not (0.0 <= score <= 1.0): score = 0.0 # Clamp score
            except (ValueError, TypeError):
                 logger.warning(f"LLM returned invalid evasion_score: {score}. Defaulting to 0.")
                 score = 0.0

            if not isinstance(flags, list):
                 logger.warning(f"LLM returned invalid type for evasion_flags: {type(flags)}. Defaulting to empty list.")
                 flags = []

            return {
                'evasion_score': round(score, 3),
                'evasion_flags': [str(f).upper().replace(" ","_") for f in flags if isinstance(f, (str, int, float))], # Standardize flags
                'explanation': explanation,
                'error': None
            }
        elif llm_response['status'] == 'success' and isinstance(llm_response['result'], str):
             logger.warning(f"LLM evasion check returned string instead of JSON: {llm_response['result'][:200]}...")
             # Attempt simple parse or return default error
             score = 0.5 if "evasive" in llm_response['result'].lower() else 0.0
             explanation = "LLM analysis inconclusive (format error)."
             flags = ["LLM_FORMAT_ERROR"]
             return {'evasion_score': score, 'evasion_flags': flags, 'explanation': explanation, 'error': "LLM JSON format error"}
        else:
            # Handle API errors or blocked content
            logger.error(f"LLM evasion check failed. Error: {llm_response.get('error')}")
            default_response['error'] = llm_response.get('error', 'Unknown LLM API error')
            if llm_response.get('blocked'):
                 default_response['explanation'] = f"Analysis blocked by content safety filter: {llm_response.get('block_reason')}"
            return default_response


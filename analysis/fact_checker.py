# File: Oppo/analysis/fact_checker.py
# Purpose: Performs fact-checking against external sources (placeholder)

import logging
import requests # For making API calls
import os
import re
from typing import Dict, List, Optional, Any, Tuple

# Use config from a2a_host package - assumes standard project structure
# Adjust relative path if necessary
try:
    from a2a_host.config import GOOGLE_API_KEY # Example: Assuming key is defined in central config
except ImportError:
     # Fallback if running standalone or structure differs
     logger = logging.getLogger(__name__) # Need logger instance here
     logger.warning("Could not import config from a2a_host. Attempting to load GOOGLE_API_KEY from environment.")
     GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Configuration ---
# Using Google Fact Check API - requires API Key and enabling the API in Google Cloud Console
# See: https://developers.google.com/fact-check/tools/api
FACT_CHECK_API_ENDPOINT = "https://factchecktools.googleapis.com/v1alpha1/claims:search"
REQUEST_TIMEOUT = 20 # Seconds timeout for external API call

# Keywords that might indicate a verifiable claim
CLAIM_KEYWORDS = [
    "percent", "%", "million", "billion", "trillion", "study shows", "data proves",
    "report finds", "increase by", "decrease by", "statistic", "poll shows", "survey finds",
    "record high", "record low", "average of", "rate of", "number of", "majority of",
    "half of", "quarter of", "voted for", "voted against", "sponsored bill", "authored"
]
MIN_CLAIM_LENGTH = 20 # Minimum characters for a sentence to be considered a potential claim
MAX_CLAIMS_PER_TEXT = 3 # Limit number of claims checked per input text

# Mapping from API rating text (lowercase) to our standardized ratings
# This needs adjustment based on observed API responses
RATING_MAP = {
    # False / Mostly False
    "false": "Verified - False",
    "pants on fire": "Verified - False",
    "four pinocchios": "Verified - False",
    "incorrect": "Verified - False",
    "untrue": "Verified - False",
    "baseless": "Verified - False",
    "scam": "Verified - False",
    "mostly false": "Verified - False",
    # True / Mostly True
    "true": "Verified - True",
    "mostly true": "Verified - True",
    "correct": "Verified - True",
    "accurate": "Verified - True",
    # Mixed / Misleading
    "partly true": "Verified - Mixed",
    "partly false": "Verified - Mixed",
    "half true": "Verified - Mixed",
    "mixture": "Verified - Mixed",
    "misleading": "Verified - Mixed",
    "exaggerated": "Verified - Mixed",
    "distorted": "Verified - Mixed",
    "needs context": "Verified - Mixed",
    # Unproven / Unverifiable
    "unproven": "Not Found / Unverifiable",
    "unsupported": "Not Found / Unverifiable",
    "no evidence": "Not Found / Unverifiable",
    "unverifiable": "Not Found / Unverifiable",
    # Other potentially relevant ratings
    "outdated": "Outdated",
    # Add more mappings as discovered
}


class FactChecker:
    """
    Performs fact-checking using external APIs (currently placeholder for Google Fact Check API).
    """
    def __init__(self, api_key: Optional[str] = GOOGLE_API_KEY):
        """Initializes the FactChecker."""
        self.api_key = api_key
        if not self.api_key:
            logger.warning("FactChecker initialized without GOOGLE_API_KEY. External fact-checking disabled.")
        else:
            logger.info("FactChecker initialized.")
        self.session = requests.Session() # Use session for potential connection reuse
        self.session.headers.update({"Accept": "application/json"})

    def _identify_claims(self, text: str) -> List[str]:
        """
        Identifies potential verifiable claims within text.
        Placeholder: Treat sentences containing numbers or keywords as claims.
        """
        claims = []
        if not text: return claims
        if not isinstance(text, str):
             logger.warning(f"Fact checker received non-string input: {type(text)}")
             return claims

        # Split into sentences (simple split, consider NLTK/SpaCy for robustness)
        sentences = re.split(r'(?<=[.!?])\s+', text)

        for sentence in sentences:
            cleaned_sentence = sentence.strip()
            if len(cleaned_sentence) < MIN_CLAIM_LENGTH:
                continue

            sentence_lower = cleaned_sentence.lower()
            # Check for digits or keywords
            if any(char.isdigit() for char in cleaned_sentence) or any(kw in sentence_lower for kw in CLAIM_KEYWORDS):
                claims.append(cleaned_sentence)
                logger.debug(f"Identified potential claim: {cleaned_sentence}")
                if len(claims) >= MAX_CLAIMS_PER_TEXT:
                    break # Stop after finding max number of claims

        # If no specific claims found, maybe check the whole text if it's reasonably short?
        if not claims and len(text) < 250 and len(text) >= MIN_CLAIM_LENGTH:
            logger.debug(f"No specific claims found, using full text as claim: {text[:100]}...")
            claims.append(text)

        logger.info(f"Identified {len(claims)} potential claims for fact-checking.")
        return claims

    def _query_fact_check_api(self, claim: str) -> Optional[Dict[str, Any]]:
        """Queries the configured external Fact Check API."""
        if not self.api_key:
            logger.debug("Skipping fact check API query: API key not configured.")
            return None
        if not claim:
            logger.debug("Skipping fact check API query: No claim provided.")
            return None

        params = {
            'query': claim,
            'key': self.api_key,
            'languageCode': 'en-US', # Make configurable?
        }
        logger.info(f"Querying Fact Check API for claim: '{claim[:100]}...'")
        try:
            response = self.session.get(FACT_CHECK_API_ENDPOINT, params=params, timeout=REQUEST_TIMEOUT)
            if response.status_code == 429: # Rate limit error
                 logger.warning(f"Fact Check API rate limit hit for claim: '{claim[:100]}...'")
                 return {"error": "Rate limit exceeded"} # Special dict to indicate rate limit
            response.raise_for_status() # Raise HTTPError for other bad responses (4xx or 5xx)
            results = response.json()
            claim_count = len(results.get('claims', []))
            logger.debug(f"Fact Check API returned {claim_count} claims for query.")
            return results
        except requests.exceptions.Timeout:
             logger.error(f"Timeout querying Fact Check API for claim: {claim[:100]}...")
             return {"error": "Timeout"}
        except requests.exceptions.HTTPError as e:
             logger.error(f"HTTP Error querying Fact Check API for claim '{claim[:100]}...': {e.response.status_code} {e.response.text[:200]}", exc_info=False)
             return {"error": f"HTTP Error {e.response.status_code}"}
        except requests.exceptions.RequestException as e:
            logger.error(f"Network Error querying Fact Check API for claim '{claim[:100]}...': {e}", exc_info=False)
            return {"error": "Network Error"}
        except Exception as e:
             logger.error(f"Unexpected error processing Fact Check API response for '{claim[:100]}...': {e}", exc_info=True)
             return {"error": "Unexpected Error"}

    def _interpret_api_results(self, api_results: Optional[Dict[str, Any]]) -> Tuple[str, List[str]]:
        """
        Analyzes the results from the Fact Check API to determine a likely rating.

        Returns:
            Tuple[str, List[str]]: (Rating String, List of Evidence URLs)
            Ratings: "Not Found / Unverifiable", "Verified - True", "Verified - False", "Verified - Mixed", "API Error", "Outdated"
        """
        status = "Not Found / Unverifiable" # Default if no conclusive claims/reviews found
        evidence_urls = set()

        if api_results is None or api_results.get("error"):
            error_type = api_results.get("error", "Unknown API Error") if api_results else "Unknown API Error"
            logger.warning(f"Fact check interpretation skipped due to API error: {error_type}")
            return "API Error", []
        if 'claims' not in api_results or not api_results['claims']:
            logger.debug("No claims found in API response.")
            return status, []

        # Aggregate results from top claim reviews (can be complex)
        # Simple approach: Iterate through all reviews in the first returned claim
        top_claim = api_results['claims'][0]
        claim_reviews = top_claim.get('claimReview', [])
        if not claim_reviews:
             logger.debug(f"No claim reviews found for claim text: {top_claim.get('text')[:100]}...")
             return status, []

        logger.debug(f"Analyzing {len(claim_reviews)} claim reviews...")
        found_ratings = []
        for review in claim_reviews:
            rating_text = review.get('textualRating', '').lower().strip()
            mapped_rating = RATING_MAP.get(rating_text)
            if mapped_rating:
                 found_ratings.append(mapped_rating)
            else:
                 if rating_text: logger.debug(f"Unmapped textualRating found: '{rating_text}'")

            url = review.get('url')
            if url:
                 evidence_urls.add(url)

        if not found_ratings:
             logger.debug("No mappable textual ratings found in claim reviews.")
             return status, sorted(list(evidence_urls)) # Return URLs even if no rating

        # Determine overall status based on priority: False > Mixed > True > Outdated > Not Found
        if "Verified - False" in found_ratings:
            status = "Verified - False"
        elif "Verified - Mixed" in found_ratings:
            status = "Verified - Mixed"
        elif "Verified - True" in found_ratings:
            status = "Verified - True"
        elif "Outdated" in found_ratings:
             status = "Outdated"
        # else status remains "Not Found / Unverifiable"

        logger.debug(f"Interpreted fact check status: '{status}' based on found ratings: {found_ratings}")
        return status, sorted(list(evidence_urls))


    def check_statement(self, text_content: Optional[str]) -> Dict[str, Any]:
        """
        Attempts to fact-check verifiable claims within a statement text.

        Args:
            text_content: The statement text to check.

        Returns:
            Dict: e.g., {'fact_check_rating': str, 'fact_check_evidence': List[str]}
                  Ratings: "Not Checked", "No Content", "No Claims Found", "API Error",
                           "Not Found / Unverifiable", "Verified - True", "Verified - False",
                           "Verified - Mixed", "Outdated"
        """
        result = {'fact_check_rating': 'Not Checked', 'fact_check_evidence': []}
        if not self.api_key:
            logger.warning("Fact check skipped: API key not available.")
            return result # 'Not Checked'
        if not text_content:
            logger.debug("Fact check skipped: No text content provided.")
            result['fact_check_rating'] = 'No Content'
            return result

        logger.info(f"Attempting fact-check for text: {text_content[:100]}...")
        claims_to_check = self._identify_claims(text_content)

        if not claims_to_check:
            logger.info("No verifiable claims identified in the text.")
            result['fact_check_rating'] = 'No Claims Found'
            return result

        overall_status = "Not Found / Unverifiable" # Default if checks run but find nothing conclusive
        all_evidence = set()
        api_error_occurred = False

        for claim in claims_to_check:
            api_results = self._query_fact_check_api(claim)
            status, evidence = self._interpret_api_results(api_results)
            all_evidence.update(evidence)

            # Update overall status based on priority (most severe finding wins)
            if status == "API Error":
                api_error_occurred = True
                overall_status = "API Error"
                break # Stop checking if API fails critically
            elif status == "Verified - False":
                overall_status = "Verified - False"
                # Optionally break here if one false claim is enough
                # break
            elif status == "Verified - Mixed" and overall_status not in ["Verified - False"]:
                 overall_status = "Verified - Mixed"
            elif status == "Verified - True" and overall_status in ["Not Found / Unverifiable", "Outdated"]:
                 overall_status = "Verified - True"
            elif status == "Outdated" and overall_status == "Not Found / Unverifiable":
                 overall_status = "Outdated"

        # Final result assignment
        result['fact_check_rating'] = overall_status
        result['fact_check_evidence'] = sorted(list(all_evidence))

        if api_error_occurred:
            logger.error(f"Fact check completed with API errors.")
        else:
            logger.info(f"Fact check completed. Overall rating: '{overall_status}'")

        return result

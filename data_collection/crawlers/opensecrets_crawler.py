# File: Oppo/data_collection/crawlers/opensecrets_crawler.py
# Purpose: Crawler for OpenSecrets.org data (Campaign Finance, Lobbying) using their API.
# Note: Kept for completeness. Needs scheduling & MCP integration. Requires API Key.

import logging
import requests
import os
import time
from typing import Dict, List, Any, Optional

# Use config from a2a_host package
try:
    # Assumes config.py is available via PYTHONPATH or project structure
    from a2a_host.config import OPENSECRETS_API_KEY, LOG_LEVEL
    CONFIG_LOADED = True
except ImportError as e:
     # Fallback for standalone use or different structure
     logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(name)s - %(message)s')
     logger = logging.getLogger(__name__) # Need logger instance here
     logger.warning(f"Could not import config from a2a_host ({e}). Loading OPENSECRETS_API_KEY from environment.")
     OPENSECRETS_API_KEY = os.getenv("OPENSECRETS_API_KEY")
     LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
     CONFIG_LOADED = True # Assume loaded from env if import fails

# Ensure logging is configured before use
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format='%(asctime)s:%(levelname)s:%(name)s:%(lineno)d:%(message)s',
    force=True # Reconfigure if needed
)
logger = logging.getLogger(__name__)
logging.getLogger("requests").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)


class OpenSecretsCrawler:
    """
    Crawler for OpenSecrets.org data using their REST API.
    Requires an API key. See: https://www.opensecrets.org/api/
    """

    BASE_URL = "https://www.opensecrets.org/api/"
    REQUEST_DELAY = 1.2 # Be relatively conservative with OpenSecrets

    def __init__(self, api_key: Optional[str] = OPENSECRETS_API_KEY):
        """
        Initializes the OpenSecrets crawler.
        Args:
            api_key: The API key for OpenSecrets. If None, loads from config/env.
        """
        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/json", # Assuming API returns JSON
            "User-Agent": "Oppo_A2A_Host/0.1 (OpenSecrets Data Collection)"
        })
        if not self.api_key:
            logger.error("OPENSECRETS_API_KEY not provided or found. OpenSecrets Crawler cannot function.")
            # Allow instantiation but methods will fail
        else:
            logger.info("OpenSecretsCrawler initialized.")

    def _make_request(self, params: Dict[str, Any]) -> Optional[Dict]:
        """Makes a request to the OpenSecrets API."""
        if not self.api_key:
            logger.error("Cannot make OpenSecrets request: API key missing.")
            return None

        # Add API key and ensure output is JSON
        base_params = { "apikey": self.api_key, "output": "json" }
        base_params.update(params)

        method = base_params.get('method', 'unknown')
        log_params = {k:v for k,v in base_params.items() if k!='apikey'}
        logger.debug(f"OpenSecrets API Request: Method={method} PARAMS: {log_params}")
        time.sleep(self.REQUEST_DELAY) # Enforce delay BEFORE request

        try:
            response = self.session.get(self.BASE_URL, params=base_params, timeout=45) # Longer timeout?
            # OpenSecrets might not use standard HTTP error codes for all issues
            # Check response content for error messages if status is 200 but data is bad
            if response.status_code == 200:
                 try:
                      data = response.json()
                      # Check for common error patterns within the JSON response
                      if isinstance(data, dict) and 'error' in data:
                           logger.error(f"OpenSecrets API returned error for method {method}: {data['error']}")
                           return None
                       # Check if 'response' key exists, as data is usually nested there
                       if isinstance(data, dict) and 'response' in data:
                            return data.get('response') # Return the 'response' part
                       else:
                            # Handle unexpected successful response format
                            logger.warning(f"Unexpected JSON structure from OpenSecrets method {method} (no 'response' key): {str(data)[:200]}")
                            return None # Assume failure if structure is wrong
                 except ValueError: # JSON decode error
                      logger.error(f"Failed to decode JSON response from OpenSecrets method {method}. Status: {response.status_code}, Text: {response.text[:200]}")
                      return None
            elif response.status_code == 403:
                 logger.error(f"OpenSecrets API returned 403 Forbidden for method {method}. Check API key validity and permissions.")
                 return None
            elif response.status_code == 429:
                 logger.warning(f"OpenSecrets API rate limit likely hit for method {method}. Pausing...")
                 time.sleep(60) # Pause
                 return None # Indicate failure, don't retry automatically here
            else:
                response.raise_for_status() # Raise for other 4xx/5xx errors
                # This line likely won't be reached if raise_for_status fails
                return response.json().get('response')

        except requests.exceptions.Timeout:
            logger.error(f"Timeout requesting OpenSecrets method: {method}")
            return None
        except requests.exceptions.RequestException as e:
            logger.error(f"Error requesting OpenSecrets method {method}: {e}", exc_info=False)
            if e.response is not None:
                logger.error(f"Response Status: {e.response.status_code}, Body: {e.response.text[:200]}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error during OpenSecrets request (Method: {method}): {e}", exc_info=True)
            return None


    # --- Specific Data Fetching Methods ---
    # Note: These map to OpenSecrets API methods. Response parsing extracts relevant parts.

    def get_legislators(self, state_id: str) -> List[Dict]:
        """Get legislators' basic info for a specific state ID (e.g., 'TX')."""
        if not self.api_key: return []
        logger.info(f"Fetching OpenSecrets legislators for state: {state_id}")
        params = {'method': 'getLegislators', 'id': state_id}
        response_data = self._make_request(params)
        # Structure: {'legislator': [{'@attributes': {...}}, ...]} or {'legislator': {'@attributes': {...}}}
        legislator_data = response_data.get('legislator', []) if isinstance(response_data, dict) else []
        if isinstance(legislator_data, dict): # Handle single result case
             legislator_data = [legislator_data]
        # Extract the attributes from each legislator entry
        return [leg.get('@attributes', {}) for leg in legislator_data if isinstance(leg, dict)]

    def get_member_profile_summary(self, cid: str, cycle: int = 2024) -> Optional[Dict]:
        """Fetch profile financial summary for a member by CID."""
        if not self.api_key: return None
        logger.info(f"Fetching OpenSecrets profile summary for CID: {cid}, cycle: {cycle}")
        params = {'method': 'memPFDSummary', 'cid': cid, 'cycle': cycle}
        response_data = self._make_request(params)
        # Response: {'summary': {'@attributes': {...}}}
        return response_data.get('summary', {}).get('@attributes') if isinstance(response_data, dict) else None

    def get_candidate_summary(self, cid: str, cycle: int = 2024) -> Optional[Dict]:
        """Fetch financial summary for a candidate by CID."""
        if not self.api_key: return None
        logger.info(f"Fetching OpenSecrets candidate summary for CID: {cid}, cycle: {cycle}")
        params = {'method': 'candSummary', 'cid': cid, 'cycle': cycle}
        response_data = self._make_request(params)
         # Response: {'summary': {'@attributes': {...}}}
        return response_data.get('summary', {}).get('@attributes') if isinstance(response_data, dict) else None

    def get_candidate_contributors(self, cid: str, cycle: int = 2024) -> List[Dict]:
        """Fetch top aggregate contributors (by organization) for a candidate by CID."""
        if not self.api_key: return []
        logger.info(f"Fetching OpenSecrets top contributors for CID: {cid}, cycle: {cycle}")
        params = {'method': 'candContrib', 'cid': cid, 'cycle': cycle}
        response_data = self._make_request(params)
        # Response: {'contributors': {'@attributes': {...}, 'contributor': [list] or dict}}
        contributors_data = response_data.get('contributors', {}) if isinstance(response_data, dict) else {}
        contributors = contributors_data.get('contributor', [])
        if isinstance(contributors, dict): # Handle single result
             contributors = [contributors]
        # Extract the attributes from each contributor entry
        return [contrib.get('@attributes', {}) for contrib in contributors if isinstance(contrib, dict)]

    def get_candidate_industries(self, cid: str, cycle: int = 2024) -> List[Dict]:
        """Fetch top industry contributions for a candidate by CID."""
        if not self.api_key: return []
        logger.info(f"Fetching OpenSecrets top industries for CID: {cid}, cycle: {cycle}")
        params = {'method': 'candIndustry', 'cid': cid, 'cycle': cycle}
        response_data = self._make_request(params)
        # Response: {'industries': {'@attributes': {...}, 'industry': [list] or dict}}
        industries_data = response_data.get('industries', {}) if isinstance(response_data, dict) else {}
        industries = industries_data.get('industry', [])
        if isinstance(industries, dict): # Handle single result
             industries = [industries]
        # Extract the attributes from each industry entry
        return [ind.get('@attributes', {}) for ind in industries if isinstance(ind, dict)]

    def get_candidate_sectors(self, cid: str, cycle: int = 2024) -> List[Dict]:
        """Fetch top sector contributions for a candidate by CID."""
        if not self.api_key: return []
        logger.info(f"Fetching OpenSecrets top sectors for CID: {cid}, cycle: {cycle}")
        params = {'method': 'candSector', 'cid': cid, 'cycle': cycle}
        response_data = self._make_request(params)
        # Response: {'sectors': {'@attributes': {...}, 'sector': [list] or dict}}
        sectors_data = response_data.get('sectors', {}) if isinstance(response_data, dict) else {}
        sectors = sectors_data.get('sector', [])
        if isinstance(sectors, dict): # Handle single result
             sectors = [sectors]
        # Extract the attributes from each sector entry
        return [sec.get('@attributes', {}) for sec in sectors if isinstance(sec, dict)]

    # Add methods for other OpenSecrets endpoints as needed (e.g., committees, lobbying - candIndByInd, orgSummary)

    def close(self):
        """Closes the requests session."""
        if self.session:
            self.session.close()
        logger.info("OpenSecretsCrawler session closed.")

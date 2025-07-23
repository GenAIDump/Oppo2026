# File: Oppo/data_collection/crawlers/congress_crawler.py
# Purpose: Crawler for Congress.gov legislative data (members, votes, bills).
# Note: Kept for completeness. Needs scheduling & MCP integration. API key optional but recommended.

import logging
import requests
import os
import time
from typing import Dict, List, Optional, Any
from urllib.parse import urljoin

# Use config from a2a_host package
try:
    from a2a_host.config import CONGRESS_API_KEY, LOG_LEVEL # CONGRESS_API_KEY might not exist/be needed
    CONFIG_LOADED = True
except ImportError as e:
     logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(name)s - %(message)s')
     logger = logging.getLogger(__name__) # Need logger instance here
     logger.warning(f"Could not import config from a2a_host ({e}). Loading CONGRESS_API_KEY from environment.")
     CONGRESS_API_KEY = os.getenv("CONGRESS_API_KEY") # API key may not be required for basic usage
     LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
     CONFIG_LOADED = True # Assume loaded from env if import fails

# Ensure logging is configured before use
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format='%(asctime)s:%(levelname)s:%(name)s:%(lineno)d:%(message)s'
)
logger = logging.getLogger(__name__)
logging.getLogger("requests").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)


class CongressCrawler:
    """
    Crawler for Congress.gov legislative data using their API.
    API Documentation: https://api.congress.gov/
    Note: Congress.gov API key enhances rate limits but basic access often works without one.
    """

    BASE_URL = "https://api.congress.gov/v3"
    CONGRESS_WEBSITE_URL = "https://www.congress.gov/" # For potential scraping fallbacks
    REQUEST_DELAY = 0.6 # Be slightly more conservative than FEC
    DEFAULT_LIMIT = 100 # Default number of results per page for API calls supporting pagination
    MAX_PAGES_PER_ENDPOINT = 10 # Limit pages to check per call

    def __init__(self, api_key: Optional[str] = CONGRESS_API_KEY):
        """
        Initializes the Congress.gov crawler.
        Args:
            api_key: Optional API key for Congress.gov. Enhances rate limits.
        """
        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/json",
            "User-Agent": "Oppo_A2A_Host/0.1 (Congress Data Collection)" # Identify your bot
        })
        if self.api_key:
            # API key is typically passed as a header 'X-Api-Key'
            self.session.headers.update({"X-Api-Key": self.api_key})
            logger.info("CongressCrawler initialized with API Key.")
        else:
            logger.warning("CongressCrawler initialized without API Key. Rate limits may be lower.")

    def _make_request(self, endpoint: str, params: Optional[Dict] = None) -> Optional[Dict]:
        """Makes a request to the Congress.gov API."""
        url = f"{self.BASE_URL}{endpoint}"
        request_params = params if params else {}

        logger.debug(f"Congress API Request: GET {url} PARAMS: {request_params}")
        time.sleep(self.REQUEST_DELAY)

        try:
            response = self.session.get(url, params=request_params, timeout=30)
            if response.status_code == 429:
                 logger.warning(f"Congress API rate limit likely hit ({endpoint}). Consider adding API Key or slowing down.")
                 retry_after = response.headers.get('Retry-After')
                 wait_time = int(retry_after) if retry_after and retry_after.isdigit() else 60
                 logger.warning(f"Pausing for {wait_time} seconds due to rate limit.")
                 time.sleep(wait_time)
                 # Simple retry once
                 response = self.session.get(url, params=request_params, timeout=30)
                 if response.status_code == 429:
                      logger.error(f"Congress API rate limit hit again after pause for {endpoint}. Aborting request.")
                      return None

            response.raise_for_status() # Raises HTTPError for other 4xx/5xx
            return response.json()
        except requests.exceptions.Timeout:
            logger.error(f"Timeout requesting Congress endpoint: {endpoint}")
            return None
        except requests.exceptions.HTTPError as e:
             logger.error(f"HTTP Error requesting Congress endpoint {endpoint}: {e.response.status_code} {e.response.text[:200]}", exc_info=False)
             return None
        except requests.exceptions.RequestException as e:
            logger.error(f"Network Error requesting Congress endpoint {endpoint}: {e}", exc_info=False)
            return None
        except Exception as e:
            logger.error(f"Unexpected error during Congress request to {endpoint}: {e}", exc_info=True)
            return None

    def _fetch_paginated_api_results(self, endpoint: str, result_key: str, params: Optional[Dict] = None, max_results: Optional[int] = None) -> List[Dict[str, Any]]:
        """Fetches results from a paginated Congress.gov endpoint (using offset/limit)."""
        all_results = []
        current_params = params.copy() if params else {}
        # API uses 'limit' and 'offset'
        page_limit = min(self.DEFAULT_LIMIT, max_results or self.DEFAULT_LIMIT*self.MAX_PAGES_PER_ENDPOINT)
        current_params['limit'] = page_limit
        current_params['offset'] = 0

        max_items = max_results if max_results is not None else float('inf')
        # Calculate max pages based on desired items AND overall limit
        max_pages_for_items = (int(max_items) + page_limit - 1) // page_limit if max_results else self.MAX_PAGES_PER_ENDPOINT
        max_pages = min(max_pages_for_items, self.MAX_PAGES_PER_ENDPOINT)

        logger.info(f"Fetching paginated Congress results for {endpoint}, key:'{result_key}', limit/page: {page_limit}, max pages: {max_pages}")

        for page_num in range(max_pages):
            current_params['offset'] = page_num * page_limit
            logger.debug(f"Fetching page {page_num + 1} with offset {current_params['offset']}...")

            data = self._make_request(endpoint, current_params)

            if not data: # Network error or API error occurred
                logger.error(f"Stopping pagination for {endpoint} due to fetch error on page {page_num + 1}.")
                break

            results = data.get(result_key, [])
            if not isinstance(results, list):
                 logger.warning(f"Unexpected data structure in pagination response for {endpoint}. Expected list under '{result_key}'. Found: {type(results)}")
                 results = []

            if not results and page_num > 0: # If page > 0 returns empty results list, we're done
                logger.info(f"Empty results on page {page_num + 1}, stopping pagination for {endpoint}.")
                break

            all_results.extend(results)
            logger.info(f"Fetched {len(results)} results on page {page_num + 1} for {endpoint}. Total: {len(all_results)}")

            if len(all_results) >= max_items:
                 logger.info(f"Reached max_results limit ({max_items}) for {endpoint}.")
                 all_results = all_results[:int(max_items)]
                 break

            pagination_info = data.get('pagination', {})
            count = pagination_info.get('count')
            # Stop if count is less than limit, indicating last page realistically
            if count is not None and count < page_limit:
                 logger.debug(f"Count ({count}) less than limit ({page_limit}), assuming last page for {endpoint}.")
                 break
            # Also check 'next' URL presence if available (API might not always include it reliably)
            if 'next' not in pagination_info or not pagination_info.get('next'):
                 logger.debug(f"No 'next' link in pagination, assuming last page for {endpoint}.")
                 break

        if len(all_results) >= page_limit * max_pages:
             logger.warning(f"Reached maximum page limit ({max_pages}) for {endpoint}. More results might exist.")

        return all_results


    # --- Specific Data Fetching Methods ---

    def get_members_current(self, chamber: Optional[str] = 'house', limit: int = 500) -> List[Dict]:
        """Gets currently serving members of a specific chamber."""
        logger.info(f"Fetching current members for chamber: {chamber}")
        endpoint = "/member"
        # Fetch more initially for filtering as API default is current members
        # Limit fetch based on input limit to be efficient
        results = self._fetch_paginated_api_results(endpoint, result_key='members', max_results=limit*2) # Fetch a bit more for filtering
        if chamber:
             chamber_lower = chamber.lower()
             # Member structure has 'terms' list, check the last term's chamber
             filtered_results = [
                 m for m in results
                 if m.get('terms') and isinstance(m['terms'], list) and m['terms']
                 and m['terms'][-1].get('chamber','').lower() == chamber_lower
             ]
             logger.info(f"Filtered {len(results)} total members down to {len(filtered_results)} for chamber '{chamber}'.")
             return filtered_results[:limit] # Return up to requested limit
        return results[:limit]


    def get_member_votes(self, bioguide_id: str, congress: Optional[int] = None, max_votes: int = 200) -> List[Dict]:
        """Fetch recent voting record for a member of Congress."""
        logger.info(f"Fetching recent votes for member {bioguide_id}, congress: {congress or 'all'}, limit: {max_votes}")
        endpoint = f"/member/{bioguide_id}/votes"
        params = {}
        if congress:
            params['congress'] = congress
        # The result key is 'votes'
        return self._fetch_paginated_api_results(endpoint, result_key='votes', params=params, max_results=max_votes)

    def get_bill_details(self, congress: int, bill_type: str, bill_number: int) -> Optional[Dict]:
        """Fetch information about a specific bill."""
        logger.info(f"Fetching details for bill {congress}-{bill_type}-{bill_number}")
        bill_type_lower = bill_type.lower()
        endpoint = f"/bill/{congress}/{bill_type_lower}/{bill_number}"
        data = self._make_request(endpoint)
        # Result key is 'bill'
        return data.get('bill') if data else None

    def get_recent_house_bills(self, congress: Optional[int] = None, limit: int = 100) -> List[Dict]:
        """Gets recently introduced or updated House bills for a given congress."""
        # Determine current or recent congress if not specified
        current_congress = congress
        if not current_congress:
             # Simple logic: assume current year corresponds roughly
             current_year = datetime.now().year
             current_congress = 118 + (current_year - 2023) // 2 # Rough calculation for 118th (2023-24)
             logger.info(f"No congress specified, defaulting to estimated current: {current_congress}")

        logger.info(f"Fetching recent House bills for Congress {current_congress}, limit: {limit}")
        endpoint = "/bill"
        params = {
            'congress': current_congress,
            'type': 'hr' # Filter for House Resolutions
            # 'sort': 'updateDate+desc' # Check API docs for valid sort fields/syntax if needed
        }
        # Result key is 'bills'
        return self._fetch_paginated_api_results(endpoint, result_key='bills', params=params, max_results=limit)

    # Note: Committee assignments might still require scraping congress.gov website pages if not in API

    def close(self):
        """Closes the requests session."""
        if self.session:
            self.session.close()
        logger.info("CongressCrawler session closed.")

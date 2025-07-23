# File: Oppo/data_collection/crawlers/fec_crawler.py
# Purpose: Crawler for FEC.gov campaign finance data using their API.
# Note: Kept for completeness. Needs scheduling & MCP integration. Requires API Key.

import logging
import requests
import os
from datetime import datetime
from typing import Dict, List, Optional, Any
import time

# Use config from a2a_host package - assumes standard project structure
try:
    # Assumes config.py is available via PYTHONPATH or project structure
    from a2a_host.config import FEC_API_KEY, LOG_LEVEL
    CONFIG_LOADED = True
except ImportError as e:
     # Fallback for standalone use or different structure
     logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(name)s - %(message)s')
     logger = logging.getLogger(__name__) # Need logger instance here
     logger.warning(f"Could not import config from a2a_host ({e}). Loading FEC_API_KEY from environment for FECCrawler.")
     FEC_API_KEY = os.getenv("FEC_API_KEY")
     LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
     CONFIG_LOADED = True # Assume loaded from env if import fails

# Ensure logging is configured before use
# Use force=True to handle potential multiple basicConfig calls
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format='%(asctime)s:%(levelname)s:%(name)s:%(lineno)d:%(message)s',
    force=True
)
logger = logging.getLogger(__name__)
logging.getLogger("requests").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)


class FECCrawler:
    """Crawler for Federal Election Commission (FEC) data via api.open.fec.gov."""

    BASE_URL = "https://api.open.fec.gov/v1"
    PAGE_SIZE = 100 # Max results per page for FEC API
    # Limit pagination to avoid excessive calls during testing/development
    MAX_PAGES_PER_ENDPOINT = 10 # Example: 10 * 100 = 1000 results max per call type
    DEFAULT_CYCLE = 2024 # Default election cycle to query
    REQUEST_DELAY = 0.5 # Seconds between paginated requests

    def __init__(self, api_key: Optional[str] = FEC_API_KEY):
        """
        Initializes the FEC crawler.
        Args:
            api_key: The API key for accessing api.open.fec.gov. If None, loads from config/env.
        """
        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "application/json",
            "User-Agent": "Oppo_A2A_Host/0.1 (FEC Data Collection)"
            })
        if not self.api_key:
            logger.error("FEC_API_KEY not provided or found in environment. FEC Crawler cannot function.")
            # Allow instantiation but methods will fail
        else:
            logger.info("FECCrawler initialized.")

    def _make_request(self, endpoint: str, params: Optional[Dict] = None) -> Optional[Dict]:
        """Makes a request to the FEC API, handling common errors."""
        if not self.api_key:
            logger.error("FEC API Key missing, cannot make request.")
            return None

        url = f"{self.BASE_URL}{endpoint}"
        request_params = {"api_key": self.api_key}
        if params:
            request_params.update(params)

        log_params = {k:v for k,v in request_params.items() if k != 'api_key'}
        logger.debug(f"FEC API Request: GET {url} PARAMS: {log_params}")

        try:
            response = self.session.get(url, params=request_params, timeout=30)
            if response.status_code == 429:
                logger.warning(f"FEC API rate limit likely hit ({endpoint}). Pausing...")
                time.sleep(60) # Standard pause for rate limits
                # Simple retry once
                response = self.session.get(url, params=request_params, timeout=30)
                if response.status_code == 429:
                     logger.error(f"FEC API rate limit hit again after pause for {endpoint}. Aborting this request.")
                     return None # Give up after one retry

            response.raise_for_status() # Raises HTTPError for other 4xx/5xx
            return response.json()
        except requests.exceptions.Timeout:
            logger.error(f"Timeout requesting FEC endpoint: {endpoint}")
            return None
        except requests.exceptions.HTTPError as e:
             logger.error(f"HTTP Error requesting FEC endpoint {endpoint}: {e.response.status_code} {e.response.text[:200]}", exc_info=False)
             return None
        except requests.exceptions.RequestException as e:
            logger.error(f"Network Error requesting FEC endpoint {endpoint}: {e}", exc_info=False)
            return None
        except Exception as e:
            logger.error(f"Unexpected error during FEC request to {endpoint}: {e}", exc_info=True)
            return None

    def _fetch_paginated_results(self, endpoint: str, params: Optional[Dict] = None, max_results: Optional[int] = None) -> List[Dict[str, Any]]:
        """Fetches results from a paginated FEC endpoint up to max_results or MAX_PAGES_PER_ENDPOINT."""
        if not self.api_key: return [] # Cannot fetch without key

        all_results = []
        current_params = params.copy() if params else {}
        current_params['per_page'] = self.PAGE_SIZE
        last_indexes = None # Store the whole last_indexes dict from pagination response

        max_pages = self.MAX_PAGES_PER_ENDPOINT
        item_limit = float('inf')
        if max_results is not None:
             item_limit = max_results
             max_pages_for_items = (max_results + self.PAGE_SIZE - 1) // self.PAGE_SIZE
             max_pages = min(max_pages_for_items, self.MAX_PAGES_PER_ENDPOINT)

        logger.info(f"Fetching paginated FEC results for {endpoint}, max pages: {max_pages}, max results: {max_results or 'N/A'}")

        for page_num in range(max_pages):
            page_params = current_params.copy()
            if last_indexes:
                 page_params.update(last_indexes)
                 log_page_params = {k:v for k,v in last_indexes.items()} # Log only pagination keys
                 logger.debug(f"Fetching page {page_num + 1} using pagination params: {log_page_params}")

            data = self._make_request(endpoint, page_params)
            # Introduce delay *after* request for FEC politeness
            time.sleep(self.REQUEST_DELAY)

            if not data or 'results' not in data:
                logger.warning(f"No results or error fetching page {page_num + 1} for {endpoint}")
                break

            results = data.get('results', [])
            if not results and page_num > 0: # If page > 0 returns empty results list, we're done
                 logger.info(f"Empty results on page {page_num + 1}, stopping pagination for {endpoint}.")
                 break

            # Add results respecting max_results limit
            needed = int(item_limit) - len(all_results)
            if needed <= 0: break # Should have been caught by max_results check below, but safety check
            all_results.extend(results[:needed])
            logger.info(f"Fetched {len(results)} results on page {page_num + 1} for {endpoint}. Total collected: {len(all_results)}")

            if len(all_results) >= item_limit:
                 logger.info(f"Reached max_results limit ({item_limit}) for {endpoint}.")
                 break

            pagination = data.get('pagination', {})
            last_indexes = pagination.get('last_indexes') # Get the dict containing keys for next page

            # Check if last_indexes exist and if there's likely a next page
            count_in_page = pagination.get('count', len(results))
            if not last_indexes or count_in_page < self.PAGE_SIZE or pagination.get('page', 0) >= pagination.get('pages', 0):
                 logger.debug(f"Last page reached or pagination keys missing for {endpoint}.")
                 break


        if len(all_results) >= self.PAGE_SIZE * max_pages:
             logger.warning(f"Reached maximum page limit ({max_pages}) for {endpoint}. More results might exist.")

        return all_results

    # --- Specific Public Data Fetching Methods ---

    def get_candidate_info(self, candidate_id: str) -> Optional[Dict]:
        """Fetch detailed info for a single candidate."""
        if not self.api_key: return None
        logger.info(f"Fetching info for FEC candidate {candidate_id}")
        endpoint = f"/candidate/{candidate_id}/"
        data = self._make_request(endpoint)
        return data['results'][0] if data and data.get('results') else None

    def search_candidates(self, name_query: str, cycle: int = DEFAULT_CYCLE, office: str = 'H') -> List[Dict]:
        """Search for candidates by name, defaulting to House for the specified cycle."""
        if not self.api_key: return []
        logger.info(f"Searching FEC candidates matching '{name_query}' for {cycle} {office}")
        endpoint = "/candidates/search/"
        params = { 'q': name_query, 'cycle': cycle, 'office': office.upper() }
        # Search results are often paginated differently, check API docs. Assume not paginated here.
        data = self._make_request(endpoint, params=params)
        return data.get('results', []) if data else []

    def get_candidate_committees(self, candidate_id: str, cycle: int = DEFAULT_CYCLE) -> List[Dict]:
        """Fetch committees associated with a candidate for a specific cycle."""
        if not self.api_key: return []
        logger.info(f"Fetching committees for FEC candidate {candidate_id}, cycle {cycle}")
        endpoint = f"/candidate/{candidate_id}/committees/history/{cycle}/"
        # Limited results usually sufficient
        return self._fetch_paginated_results(endpoint, max_results=500)

    def get_committee_contributions_received(self, committee_id: str, cycle: int = DEFAULT_CYCLE, max_results: int = 500) -> List[Dict]:
        """Fetch recent contributions received *by* a specific committee (Schedule A)."""
        if not self.api_key: return []
        logger.info(f"Fetching Schedule A contributions for committee {committee_id}, cycle {cycle}, limit ~{max_results}")
        endpoint = f"/schedules/schedule_a/"
        params = {
            'committee_id': committee_id,
            'cycle': cycle,
            'sort': '-contribution_receipt_date', # Sort newest first is crucial for pagination
            'sort_hide_index': 'false' # Required for date-based pagination keys to appear
        }
        # Pagination keys for schedule_a sorted by date are 'last_index', 'last_contribution_receipt_date'
        return self._fetch_paginated_results(endpoint, params, max_results=max_results)

    def get_committee_expenditures_made(self, committee_id: str, cycle: int = DEFAULT_CYCLE, max_results: int = 500) -> List[Dict]:
        """Fetch recent expenditures made *by* a specific committee (Schedule B)."""
        if not self.api_key: return []
        logger.info(f"Fetching Schedule B expenditures for committee {committee_id}, cycle {cycle}, limit ~{max_results}")
        endpoint = f"/schedules/schedule_b/"
        params = {
            'committee_id': committee_id,
            'cycle': cycle,
            'sort': '-disbursement_date', # Sort newest first
            'sort_hide_index': 'false' # Required for date-based pagination keys
        }
        # Pagination keys for schedule_b sorted by date are 'last_index', 'last_disbursement_date'
        return self._fetch_paginated_results(endpoint, params, max_results=max_results)

    def close(self):
        """Closes the requests session."""
        if self.session:
            self.session.close()
        logger.info("FECCrawler session closed.")

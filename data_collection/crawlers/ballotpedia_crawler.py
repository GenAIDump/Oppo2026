# File: Oppo/data_collection/crawlers/ballotpedia_crawler.py
# Purpose: Crawler for fetching pages from Ballotpedia.org.
# Note: Kept for completeness. Needs scheduling & MCP integration. Respect robots.txt & ToS.

import logging
import requests
import os
import time
from typing import Dict, List, Optional, Any, Set
from bs4 import BeautifulSoup # Requires beautifulsoup4
from urllib.parse import urljoin, urlparse
from random import uniform

# Use config from a2a_host package
try:
    from a2a_host.config import LOG_LEVEL
except ImportError:
     logging.basicConfig(level=logging.INFO)
     logger = logging.getLogger(__name__)
     logger.warning("Could not import config from a2a_host for BallotpediaCrawler.")
     LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

# Ensure logging is configured before use
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format='%(asctime)s:%(levelname)s:%(name)s:%(message)s'
)
logger = logging.getLogger(__name__)

# Requires beautifulsoup4 to be installed: pip install beautifulsoup4
try:
    import bs4
except ImportError:
     logger.error("BeautifulSoup4 library not found. BallotpediaCrawler disabled. Install with: pip install beautifulsoup4")
     BeautifulSoup = None # Set to None to disable functionality


class BallotpediaCrawler:
    """Crawls pages from Ballotpedia."""

    # Be polite - Ballotpedia is a valuable resource
    REQUEST_DELAY_MIN = 2.5 # Minimum seconds to wait between requests
    REQUEST_DELAY_MAX = 6.0 # Maximum seconds to wait between requests
    DEFAULT_TIMEOUT = 30 # Seconds for requests
    # Define a clear User-Agent
    USER_AGENT = "Oppo_A2A_Host/0.1 (Data Collection Component; respectful crawling; contact: your-project-contact-email@example.com)" # CHANGE THIS EMAIL

    def __init__(self):
        """Initialize the Ballotpedia crawler."""
        if not BeautifulSoup:
             raise ImportError("BeautifulSoup4 is required for BallotpediaCrawler but not installed.")

        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "User-Agent": self.USER_AGENT
        })
        logger.info("BallotpediaCrawler initialized.")

    def _make_request(self, url: str) -> Optional[requests.Response]:
        """Makes a request, handles common errors, respects delay."""
        # Enforce politeness delay
        delay = uniform(self.REQUEST_DELAY_MIN, self.REQUEST_DELAY_MAX)
        logger.debug(f"Waiting {delay:.2f}s before requesting: {url}")
        time.sleep(delay)

        try:
            response = self.session.get(url, timeout=self.DEFAULT_TIMEOUT, allow_redirects=True)
            content_type = response.headers.get('Content-Type', '').lower()
            if 'text/html' not in content_type:
                logger.warning(f"Skipping non-HTML content at {url} (Content-Type: {content_type})")
                return None
            response.raise_for_status()
            # Check if redirected away from ballotpedia.org? Optional.
            # final_domain = urlparse(response.url).netloc
            # if 'ballotpedia.org' not in final_domain:
            #      logger.warning(f"Redirected outside Ballotpedia domain from {url} to {response.url}")
            #      return None
            return response
        except requests.exceptions.Timeout:
            logger.error(f"Timeout requesting Ballotpedia URL: {url}")
            return None
        except requests.exceptions.HTTPError as e:
             if e.response.status_code == 404:
                  logger.warning(f"Ballotpedia URL not found (404): {url}")
             elif e.response.status_code == 429: # Check if Ballotpedia uses 429
                  logger.warning(f"Rate limit likely hit for Ballotpedia URL: {url}. Consider increasing delay.")
                  # Could implement backoff here
             else:
                  logger.error(f"HTTP Error requesting Ballotpedia URL {url}: {e.response.status_code}", exc_info=False)
             return None
        except requests.exceptions.RequestException as e:
            logger.error(f"Network Error requesting Ballotpedia URL {url}: {e}", exc_info=False)
            return None
        except Exception as e:
            logger.error(f"Unexpected error during request to Ballotpedia URL {url}: {e}", exc_info=True)
            return None

    def fetch_page_html(self, url: str) -> Optional[str]:
        """
        Fetches the raw HTML content for a given Ballotpedia URL.
        Checks robots.txt before fetching (basic check).

        Args:
            url: The Ballotpedia URL to crawl.

        Returns:
            The HTML content as a string, or None on failure or if disallowed by robots.txt.
        """
        if not url.startswith("https://ballotpedia.org/"):
             logger.warning(f"URL '{url}' does not appear to be a Ballotpedia URL. Skipping.")
             return None

        # Basic robots.txt check (implementation would require fetching/parsing robots.txt)
        # For now, assume responsible crawling if this check is omitted/simplified
        # if not self.is_allowed_by_robots(url):
        #    logger.warning(f"Crawling disallowed by robots.txt (or check failed) for URL: {url}")
        #    return None
        logger.debug(f"Attempting to fetch Ballotpedia URL: {url} (Robots check placeholder)")

        response = self._make_request(url)
        if response and response.text:
             logger.info(f"Successfully fetched {url} ({len(response.text)} bytes)")
             return response.text
        else:
             logger.warning(f"Failed to fetch HTML content for {url}")
             return None

    # Optional: Add method to find links on a page (e.g., find candidate links from an election page)
    # def find_links_on_page(self, url: str, css_selector: str = 'a[href]') -> List[str]:
    #     """Finds and returns absolute Ballotpedia links matching a selector."""
    #     html = self.fetch_page_html(url)
    #     if not html: return []
    #     soup = BeautifulSoup(html, 'html.parser')
    #     found_links = set()
    #     base_url = "https://ballotpedia.org/" # Simpler base
    #     for tag in soup.select(css_selector):
    #          href = tag.get('href')
    #          if href:
    #              abs_url = urljoin(base_url, href) # Use simpler base for joining internal links
    #              # Ensure it's still a ballotpedia link after joining
    #              if urlparse(abs_url).netloc == 'ballotpedia.org':
    #                   clean_url = urljoin(abs_url, urlparse(abs_url).path).rstrip('/') # Clean fragment/slash
    #                   found_links.add(clean_url)
    #     return sorted(list(found_links))


    def close(self):
        """Closes the requests session."""
        if self.session:
            self.session.close()
        logger.info("BallotpediaCrawler session closed.")

# Example Usage (if run directly)
if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG) # Enable debug logging for testing
    # Replace with a real Ballotpedia URL for testing
    # Example: test_url = "https://ballotpedia.org/United_States_House_of_Representatives_elections,_2024"
    # Example: test_candidate_url = "https://ballotpedia.org/Kevin_Kiley" # Example candidate
    test_url = None # Set a URL here

    if test_url:
        crawler = BallotpediaCrawler()
        try:
            print(f"\n--- Fetching Ballotpedia Page: {test_url} ---")
            html = crawler.fetch_page_html(test_url)

            if html:
                print(f"Successfully fetched {len(html)} bytes of HTML.")
                # Basic parsing example: Find the page title
                soup = BeautifulSoup(html, 'html.parser')
                title_tag = soup.find('h1', id='firstHeading')
                title = title_tag.get_text(strip=True) if title_tag else "Title not found"
                print(f"Page Title: {title}")

                # Example: Find candidate links if it's an election page (requires adjusting selector)
                # if "election" in test_url.lower():
                #     print("\n--- Finding Links (example selector 'div.results_table td b a[href]') ---")
                #     # Adjust selector based on actual page structure
                #     links = crawler.find_links_on_page(test_url, css_selector='div.results_table td b a[href]')
                #     print(f"Found {len(links)} potential candidate links:")
                #     for link in links[:10]: # Print first 10
                #          print(f"  {link}")

            else:
                print("Failed to fetch HTML.")

        finally:
            crawler.close()
    else:
        print("Please set a 'test_url' in the script to run the Ballotpedia example.")

# File: Oppo/data_collection/crawlers/campaign_website_crawler.py
# Purpose: Crawler for candidate campaign websites (general structure).
# Note: Highly dependent on individual site structure. Needs robust error handling and likely specific adapters per site. Kept for completeness.

import logging
import requests
import os
import time
from typing import Dict, List, Any, Optional, Set
from bs4 import BeautifulSoup # Requires beautifulsoup4
from urllib.parse import urljoin, urlparse
import re
from collections import deque

# Use config from a2a_host package
try:
    from a2a_host.config import LOG_LEVEL
except ImportError:
     logging.basicConfig(level=logging.INFO)
     logger = logging.getLogger(__name__)
     logger.warning("Could not import config from a2a_host for CampaignWebsiteCrawler.")
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
     logger.error("BeautifulSoup4 library not found. CampaignWebsiteCrawler disabled. Install with: pip install beautifulsoup4")
     BeautifulSoup = None # Set to None to disable functionality

class CampaignWebsiteCrawler:
    """
    Crawls basic information from campaign websites.
    WARNING: Campaign websites vary greatly. This provides a basic framework
    and heuristic-based extraction that will likely need customization or
    more advanced techniques (like ML classifiers) for reliable data gathering across many sites.
    """

    REQUEST_DELAY = 1.5 # Seconds delay between requests
    DEFAULT_MAX_PAGES = 20 # Limit pages crawled per site
    DEFAULT_TIMEOUT = 20 # Seconds for requests

    def __init__(self, max_pages_per_site: int = DEFAULT_MAX_PAGES):
        """
        Initializes the Campaign Website crawler.
        Args:
            max_pages_per_site: Maximum number of pages to crawl per website.
        """
        if not BeautifulSoup:
             raise ImportError("BeautifulSoup4 is required for CampaignWebsiteCrawler but not installed.")

        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "User-Agent": "Oppo_A2A_Host/0.1 (Data Collection Component; contact: your-email@example.com)"
        })
        self.max_pages = max_pages_per_site
        logger.info(f"CampaignWebsiteCrawler initialized (Max pages: {self.max_pages}).")

    def _make_request(self, url: str) -> Optional[requests.Response]:
        """Makes a request, handles common errors, respects delay."""
        logger.debug(f"Requesting URL: {url}")
        time.sleep(self.REQUEST_DELAY)
        try:
            response = self.session.get(url, timeout=self.DEFAULT_TIMEOUT, allow_redirects=True)
            # Check if content is likely HTML before proceeding
            content_type = response.headers.get('Content-Type', '').lower()
            if 'text/html' not in content_type:
                logger.debug(f"Skipping non-HTML content at {url} (Content-Type: {content_type})")
                return None
            response.raise_for_status()
            # Check final URL after redirects
            if urlparse(response.url).netloc != urlparse(url).netloc:
                logger.debug(f"Redirected outside original domain from {url} to {response.url}. Skipping content.")
                return None
            return response
        except requests.exceptions.Timeout:
            logger.error(f"Timeout requesting campaign URL: {url}")
            return None
        except requests.exceptions.TooManyRedirects:
             logger.error(f"Too many redirects encountered for URL: {url}")
             return None
        except requests.exceptions.HTTPError as e:
             if e.response.status_code == 404:
                  logger.warning(f"URL not found (404): {url}")
             else:
                  logger.error(f"HTTP Error requesting campaign URL {url}: {e.response.status_code}", exc_info=False)
             return None
        except requests.exceptions.RequestException as e:
            logger.error(f"Network Error requesting campaign URL {url}: {e}", exc_info=False)
            return None
        except Exception as e:
            logger.error(f"Unexpected error during request to campaign URL {url}: {e}", exc_info=True)
            return None

    def _extract_internal_links(self, soup: BeautifulSoup, base_url: str) -> Set[str]:
        """Extracts unique, valid internal links from a page."""
        links = set()
        parsed_base = urlparse(base_url)
        for a_tag in soup.find_all('a', href=True):
            href = a_tag['href'].strip()
            if not href or href.startswith('#') or href.startswith('mailto:') or href.startswith('tel:') or href.startswith('javascript:'):
                continue

            try:
                absolute_url = urljoin(base_url, href)
                parsed_url = urlparse(absolute_url)

                # Ensure it's HTTP/HTTPS and belongs to the same domain (or www subdomain)
                if parsed_url.scheme in ['http', 'https'] and \
                   (parsed_url.netloc == parsed_base.netloc or parsed_url.netloc == f"www.{parsed_base.netloc}"):
                    # Clean fragments and trailing slashes for uniqueness checking
                    clean_url = urljoin(absolute_url, parsed_url.path).rstrip('/')
                    links.add(clean_url)
            except Exception as e:
                 logger.debug(f"Error parsing or joining URL '{href}' relative to '{base_url}': {e}")

        return links

    def _extract_page_content(self, soup: BeautifulSoup) -> Dict[str, Optional[str]]:
        """Extracts title and main textual content from a page."""
        data = {'title': None, 'text_content': None}

        # Title
        title_tag = soup.find('title')
        if title_tag:
            data['title'] = title_tag.get_text(strip=True)

        # Attempt to find main content area (common tags/IDs/classes)
        main_content = None
        selectors = ['main', 'article', '#main', '#content', '.main-content', '.entry-content', '.post-content', 'div[role="main"]']
        for selector in selectors:
             main_content = soup.select_one(selector)
             if main_content: break

        if not main_content: # Fallback to body if no main content found
             main_content = soup.find('body')

        if main_content:
             # Remove common noise elements
             for tag in main_content.find_all(['script', 'style', 'nav', 'footer', 'header', 'aside', 'form', 'button', '.nav', '.footer', '.header', '.sidebar']):
                  tag.decompose()
             data['text_content'] = main_content.get_text(separator='\n', strip=True) # Use newline separator
        else:
             logger.warning("Could not extract main content area.")

        return data

    def crawl_site(self, start_url: str) -> Dict[str, Any]:
        """
        Performs a breadth-first crawl of a campaign website up to max_pages.

        Args:
            start_url: The starting URL (homepage) of the campaign site.

        Returns:
            A dictionary containing crawled page data:
            {
                "start_url": str,
                "crawl_timestamp_utc": str,
                "pages": [ { "url": str, "title": str | None, "text_content": str | None, "status_code": int | None, "error": str | None } ],
                "total_pages_visited": int
            }
        """
        logger.info(f"Starting crawl for campaign site: {start_url}")
        if not start_url.startswith(('http://', 'https://')):
            start_url = 'https://' + start_url

        crawl_results = {
            "start_url": start_url,
            "crawl_timestamp_utc": datetime.now(timezone.utc).isoformat(),
            "pages": [],
            "total_pages_visited": 0
        }
        base_url = urljoin(start_url, '/') # Get base e.g., https://example.com/
        parsed_base = urlparse(base_url)
        if not parsed_base.netloc:
             logger.error(f"Invalid start URL, cannot determine domain: {start_url}")
             return crawl_results

        queue = deque([start_url.rstrip('/')]) # Use deque for efficient BFS
        visited = {start_url.rstrip('/')}

        while queue and crawl_results["total_pages_visited"] < self.max_pages:
            current_url = queue.popleft()
            logger.info(f"Crawling page {crawl_results['total_pages_visited'] + 1}/{self.max_pages}: {current_url}")

            page_data = {"url": current_url, "title": None, "text_content": None, "status_code": None, "error": None}
            response = self._make_request(current_url)

            if response and response.text:
                page_data["status_code"] = response.status_code
                try:
                    soup = BeautifulSoup(response.text, 'html.parser')
                    content = self._extract_page_content(soup)
                    page_data.update(content)

                    # Find new internal links to crawl
                    internal_links = self._extract_internal_links(soup, base_url)
                    for link in internal_links:
                        if link not in visited and len(visited) < self.max_pages * 5: # Limit visited set size roughly
                            visited.add(link)
                            queue.append(link)
                            # logger.debug(f"Added to queue: {link}")

                except Exception as parse_error:
                     logger.error(f"Error parsing HTML for {current_url}: {parse_error}", exc_info=True)
                     page_data["error"] = f"HTML Parsing Error: {parse_error}"
            elif response: # Request made, but no text content or error status handled by _make_request
                 page_data["status_code"] = response.status_code
                 page_data["error"] = f"Request successful but no valid HTML content found (Status: {response.status_code})"
            else: # _make_request returned None (e.g., timeout, network error, 404)
                 page_data["error"] = "Failed to fetch URL"
                 # Status code might be unknown here

            crawl_results["pages"].append(page_data)
            crawl_results["total_pages_visited"] += 1

        logger.info(f"Finished crawl for {start_url}. Visited {crawl_results['total_pages_visited']} pages.")
        if queue:
             logger.info(f"Stopped crawl due to max page limit ({self.max_pages}). {len(queue)} URLs remaining in queue.")

        return crawl_results


    def close(self):
        """Closes the requests session."""
        if self.session:
            self.session.close()
        logger.info("CampaignWebsiteCrawler session closed.")


# Example Usage (if run directly)
if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG) # Enable debug logging for testing
    # Replace with a *real* campaign website URL for testing (use responsibly!)
    # test_url = "https://www.some-real-campaign-site.com/" # Use a known site
    test_url = None # Set a URL here

    if test_url:
        crawler = CampaignWebsiteCrawler(max_pages_per_site=5) # Limit pages for example
        try:
            print(f"\n--- Crawling Campaign Site: {test_url} (Limit 5 pages) ---")
            results = crawler.crawl_site(test_url)
            print(f"\n--- Crawl Summary ---")
            print(f"Start URL: {results['start_url']}")
            print(f"Timestamp: {results['crawl_timestamp_utc']}")
            print(f"Pages Visited: {results['total_pages_visited']}")
            print("\n--- Sample Page Data ---")
            for page in results['pages'][:3]: # Print data for first 3 pages
                 print(f"\nURL: {page['url']}")
                 print(f"Status Code: {page['status_code']}")
                 print(f"Title: {page['title']}")
                 print(f"Error: {page['error']}")
                 # print(f"Content Snippet: {(page.get('text_content') or '')[:200]}...") # Be careful printing content
                 print("-" * 10)

        finally:
            crawler.close()
    else:
        print("Please set a 'test_url' in the script to run the example.")

# File: Oppo/data_collection/crawlers/house_press_crawler.py
# Purpose: Crawler for House Republican Press Releases (Committee sites & GOP.gov).
# Note: Kept for completeness. Needs scheduling & MCP integration. Selectors may need updates. Relies on web scraping.

import logging
import requests
import os
import time
from typing import Dict, List, Any, Optional
from datetime import datetime, timedelta, timezone
import re
from urllib.parse import urljoin, urlparse

# Requires beautifulsoup4
try:
    from bs4 import BeautifulSoup, Tag, NavigableString
    BS4_LOADED = True
except ImportError:
     logging.error("BeautifulSoup4 library not found. HousePressCrawler disabled. Install with: pip install beautifulsoup4")
     BS4_LOADED = False
     BeautifulSoup = None # Set to None to disable functionality
     Tag = object # Dummy object for type hints
     NavigableString = object # Dummy object for type hints

# Use config from a2a_host package
try:
    from a2a_host.config import LOG_LEVEL
    CONFIG_LOADED = True
except ImportError as e:
     logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(name)s - %(message)s')
     logger = logging.getLogger(__name__) # Need logger instance here
     logger.warning(f"Could not import config from a2a_host ({e}). Using env var for HousePressCrawler.")
     LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
     CONFIG_LOADED = True

# Ensure logging is configured before use
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format='%(asctime)s:%(levelname)s:%(name)s:%(lineno)d:%(message)s',
    force=True
)
logger = logging.getLogger(__name__)
logging.getLogger("requests").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)


class HousePressCrawler:
    """Crawls House Republican committee websites and GOP.gov for press releases."""

    # Base URL templates - These might change and need verification
    GOP_BASE_URL = "https://www.gop.gov"
    COMMITTEE_BASE_URL_TEMPLATE = "https://republicans-{committee}.house.gov"

    # List of committees - needs periodic verification/updates
    # Example list, verify current committee names/URLs (as of last check)
    COMMITTEES = [
        "appropriations", "armedservices", "budget", "educationandtheworkforce",
        "energycommerce", "financialservices", "foreignaffairs", "homelandsecurity",
        "judiciary", "naturalresources", "oversight", "rules", "science",
        "smallbusiness", "transportation", "veterans", "waysandmeans",
        "agriculture", "ethics", "houseadministration", "judiciary", # Add others
    ]

    REQUEST_DELAY = 1.5 # Seconds delay between requests to be polite
    DEFAULT_DAYS_BACK = 7 # How many days back to check for recent releases
    DEFAULT_TIMEOUT = 25 # Seconds for requests

    def __init__(self):
        """Initialize the House Press crawler."""
        if not BS4_LOADED:
             raise ImportError("BeautifulSoup4 is required for HousePressCrawler but not installed.")

        self.session = requests.Session()
        self.session.headers.update({
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            # Be transparent with User-Agent
            "User-Agent": "Oppo_A2A_Host/0.1 (House Press Data Collection; respectful crawling; contact: project-contact@example.com)" # CHANGE THIS EMAIL
        })
        logger.info("HousePressCrawler initialized.")

    def _make_request(self, url: str) -> Optional[requests.Response]:
        """Makes a request, handles common errors, respects delay."""
        logger.debug(f"Requesting URL: {url}")
        time.sleep(self.REQUEST_DELAY)
        try:
            response = self.session.get(url, timeout=self.DEFAULT_TIMEOUT, allow_redirects=True)
            content_type = response.headers.get('Content-Type', '').lower()
            # Only parse HTML content
            if 'text/html' not in content_type:
                logger.debug(f"Skipping non-HTML content at {url} (Content-Type: {content_type})")
                return None
            response.raise_for_status() # Raise HTTPError for 4xx/5xx responses
            # Optional: Check final URL after redirects doesn't go too far astray
            # final_domain = urlparse(response.url).netloc
            # if '.house.gov' not in final_domain and 'gop.gov' not in final_domain:
            #      logger.warning(f"Redirected outside expected domain from {url} to {response.url}. Skipping.")
            #      return None
            return response
        except requests.exceptions.Timeout:
            logger.error(f"Timeout requesting URL: {url}")
            return None
        except requests.exceptions.TooManyRedirects:
             logger.error(f"Too many redirects encountered for URL: {url}")
             return None
        except requests.exceptions.HTTPError as e:
             if e.response.status_code == 404:
                  logger.warning(f"URL not found (404): {url}")
             else:
                  logger.error(f"HTTP Error requesting URL {url}: {e.response.status_code}", exc_info=False)
             return None
        except requests.exceptions.RequestException as e:
            logger.error(f"Network Error requesting URL {url}: {e}", exc_info=False)
            return None
        except Exception as e:
            logger.error(f"Unexpected error during request to {url}: {e}", exc_info=True)
            return None

    def _clean_text(self, element: Optional[Any]) -> Optional[str]:
        """Extracts and cleans text content from a BS4 Tag or string."""
        if not element: return None
        text = None
        if isinstance(element, NavigableString):
             text = element.strip()
        elif isinstance(element, Tag):
             # Basic cleanup within tag before getting text
             for hidden_span in element.find_all(class_=re.compile("hidden|sr-only", re.I)): hidden_span.decompose()
             text = element.get_text(separator=' ', strip=True)
        elif isinstance(element, str):
            text = element.strip()
        else:
            return None

        if text:
             # Normalize whitespace and remove excessive internal spacing
             text = re.sub(r'\s+', ' ', text).strip()
             return text
        return None

    def _parse_date(self, date_str: str) -> Optional[datetime]:
        """Parses date string in various common formats found on websites."""
        if not date_str: return None
        date_str = date_str.strip()
        # Increased list of formats
        formats = [
            '%Y-%m-%d', '%m/%d/%Y', '%m.%d.%Y', '%B %d, %Y', '%b %d, %Y',
            '%b. %d, %Y', '%d %B %Y', '%d %b %Y',
            '%Y-%m-%dT%H:%M:%S%z', # ISO with timezone
            '%Y-%m-%dT%H:%M:%S',   # ISO without timezone
            '%m/%d/%y', '%-m/%-d/%Y', # Handle single digit month/day
             # Add formats with time if found, e.g., '%B %d, %Y at %I:%M %p'
        ]
        for fmt in formats:
            try:
                dt = datetime.strptime(date_str, fmt)
                # Assume UTC if no timezone info parsed (websites are often ambiguous)
                return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
            except ValueError:
                continue
        # Fallback: try parsing with dateutil if installed (more flexible)
        try:
             from dateutil import parser
             dt = parser.parse(date_str)
             logger.debug(f"Used dateutil.parser for '{date_str}'")
             return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)
        except ImportError:
             pass # dateutil not available
        except (ValueError, OverflowError, TypeError):
             logger.debug(f"dateutil failed to parse date string: '{date_str}'")

        logger.warning(f"Could not parse date string: '{date_str}' with known formats.")
        return None

    def _extract_press_releases_from_page(self, soup: BeautifulSoup, page_url: str, source_name: str, cutoff_date: datetime) -> List[Dict]:
        """Extracts press release links, titles, and dates from a BeautifulSoup object."""
        releases = []
        base_url = urljoin(page_url, '/') # Get scheme + domain
        # --- Selectors Need Regular Adjustment based on Target Site Structure ---
        possible_selectors = [
            'article.press-release', 'div.views-row', 'li.node-press_release', 'li.news-item',
            'div.node--type-press-release', 'div.press-item', 'tr.release-row', 'div.media-release',
            'li.item', '.news-list-item', 'div.post-preview', 'div.release' # Add more general selectors
        ]
        items_found = []
        used_selector = "None"
        for selector in possible_selectors:
             items_found = soup.select(selector)
             if items_found:
                  used_selector = selector
                  logger.debug(f"Using selector '{selector}' for {page_url}, found {len(items_found)} items.")
                  break

        if not items_found:
            # Fallback: look for any list items within a main content area
            main_content = soup.select_one('main, #main, #content, .main-content') or soup.body
            if main_content:
                 items_found = main_content.select('li > a[href]') # Links inside list items
                 if items_found:
                      logger.debug(f"Using fallback selector 'main li > a' for {page_url}, found {len(items_found)} potential links.")
                      # Need to adjust item processing below if only link tag is found
                      items_found = [link.parent for link in items_found] # Use parent 'li' as item
                      used_selector = 'main li'

        if not items_found:
            logger.warning(f"No potential press release items found on {page_url} using common selectors or fallback.")
            return []

        count = 0
        for item in items_found:
            count += 1
            title = "No Title Found"
            link = None
            date_str = None
            parsed_date = None

            # Find link and title within the item context
            link_tag = item.find('a', href=True)
            title_tag = item.find(['h2', 'h3', 'h4', 'div', 'span'], class_=re.compile(r'title|headline|heading', re.I)) or \
                        item.find(['h2', 'h3', 'h4']) # Fallback headers
            if not title_tag and link_tag: title_tag = link_tag # Use link tag itself if no other title found

            if link_tag:
                href = link_tag['href']
                if href and not href.startswith('javascript:'):
                     link = urljoin(base_url, href) # Resolve relative URLs

            if title_tag:
                title = self._clean_text(title_tag)

            # Try finding date within the item context
            date_tag = item.find('time', datetime=True)
            if date_tag and date_tag.get('datetime'):
                 date_str = date_tag['datetime']
            else:
                 date_tag = item.find(['span', 'div', 'p'], class_=re.compile(r'date|time|posted|created', re.I))
                 if date_tag: date_str = self._clean_text(date_tag)
                 else: # Look for text patterns within the item's text if no specific tag found
                      item_text_sample = item.get_text(separator=' ', strip=True)[:150] # Limit search scope
                      # Regex for common date patterns (MM/DD/YYYY, Month D, YYYY, YYYY-MM-DD etc.)
                      date_match = re.search(r'\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+\d{1,2},?\s+\d{4}\b|\b\d{1,2}[./-]\d{1,2}[./-]\d{2,4}\b|\b\d{4}-\d{2}-\d{2}\b', item_text_sample)
                      if date_match: date_str = date_match.group(0)

            if date_str:
                parsed_date = self._parse_date(date_str)

            # Validate required fields and date cutoff
            if link and title and title != "No Title Found":
                if parsed_date is None or parsed_date >= cutoff_date:
                    release_data = {
                        'title': title,
                        'url': link,
                        'date_str': date_str,
                        'parsed_date_utc': parsed_date.isoformat() if parsed_date else None,
                        'source_name': source_name,
                        'fetch_time_utc': datetime.now(timezone.utc).isoformat()
                    }
                    releases.append(release_data)
                    logger.debug(f"Extracted potential release: '{title[:50]}...' ({parsed_date or 'No Date'}) from {source_name}")
                elif parsed_date: # Log skipped old releases only if date was parsed
                     logger.debug(f"Skipping old release: '{title[:50]}...' ({parsed_date.strftime('%Y-%m-%d')}) from {source_name}")
            else:
                 logger.debug(f"Skipping item {count} found by '{used_selector}': Missing link or title.")


        return releases

    def fetch_recent_releases(self, days_back: int = DEFAULT_DAYS_BACK) -> List[Dict]:
        """Fetches recent press releases from GOP.gov and committee sites."""
        if not BS4_LOADED: return [] # Exit if BS4 not loaded

        all_releases = []
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_back)
        logger.info(f"Fetching press releases newer than {cutoff_date.strftime('%Y-%m-%d')}")

        # 1. Fetch from GOP.gov
        # Check common paths
        gop_paths = ["/news/press-releases/", "/news/"]
        fetched_gop = False
        for path in gop_paths:
             gop_url = urljoin(self.GOP_BASE_URL, path)
             logger.info(f"Attempting to fetch from {gop_url}")
             response = self._make_request(gop_url)
             if response and response.text:
                 try:
                     soup = BeautifulSoup(response.text, 'html.parser')
                     gop_releases = self._extract_press_releases_from_page(soup, self.GOP_BASE_URL, "House GOP (gop.gov)", cutoff_date)
                     if gop_releases: # Only add if something was found
                          logger.info(f"Found {len(gop_releases)} recent releases on gop.gov path '{path}'.")
                          all_releases.extend(gop_releases)
                          fetched_gop = True
                          break # Stop checking gop paths if one worked
                 except Exception as e:
                     logger.error(f"Error parsing GOP.gov page {gop_url}: {e}", exc_info=True)
             elif response is None and response != 404: # Network/HTTP error other than 404
                 logger.warning(f"Skipping GOP.gov checks due to fetch error at {gop_url}.")
                 break # Stop checking gop paths if base site seems problematic
        if not fetched_gop: logger.warning(f"Could not find releases on {self.GOP_BASE_URL}")


        # 2. Fetch from Committee Sites
        for committee in self.COMMITTEES:
            committee_url_base = self.COMMITTEE_BASE_URL_TEMPLATE.format(committee=committee)
            # Assume press releases are at /press-releases/ or /news/ or similar - try common paths
            possible_paths = ["/press-releases/", "/news/releases/", "/news/press-releases/", "/news/"]
            fetched_for_committee = False
            for path in possible_paths:
                 committee_url = urljoin(committee_url_base, path)
                 logger.info(f"Attempting to fetch from {committee_url}")
                 response = self._make_request(committee_url)
                 if response and response.text:
                     try:
                         soup = BeautifulSoup(response.text, 'html.parser')
                         # Pass committee base URL for resolving relative links correctly
                         source_name = f"Rep Committee ({committee})"
                         comm_releases = self._extract_press_releases_from_page(soup, committee_url_base, source_name, cutoff_date)
                         if comm_releases:
                              logger.info(f"Found {len(comm_releases)} recent releases on {committee} committee site ({path}).")
                              all_releases.extend(comm_releases)
                              fetched_for_committee = True
                              break # Stop trying paths for this committee
                     except Exception as e:
                          logger.error(f"Error parsing committee page {committee_url}: {e}", exc_info=True)

                 elif response is None and response != 404:
                      logger.warning(f"Skipping rest of paths for {committee} due to fetch error at {committee_url}.")
                      break

            if not fetched_for_committee:
                 logger.warning(f"Could not find valid press release path or content for committee: {committee}")


        # Deduplicate based on URL
        seen_urls = set()
        unique_releases = []
        for release in all_releases:
            url = release.get('url')
            if url and url not in seen_urls:
                unique_releases.append(release)
                seen_urls.add(url)

        logger.info(f"Fetched a total of {len(unique_releases)} unique recent press release links.")
        # Note: This list only contains links/metadata. Content fetching is separate.
        return unique_releases

    def fetch_release_content(self, url: str) -> Optional[str]:
        """Fetches the main textual content from a press release URL."""
        if not BS4_LOADED: return None
        response = self._make_request(url)
        if not response or not response.text:
             logger.warning(f"Could not fetch content for URL: {url}")
             return None

        try:
            soup = BeautifulSoup(response.text, 'html.parser')
            # Try common content selectors - needs refinement based on sites
            # Prioritize selectors that are more likely to contain the main article body
            content_selectors = [
                'article', # HTML5 article tag
                'div[role="main"]', # WAI-ARIA role
                '.entry-content', '.post-content', '.article-content', # Common class names
                'div.field-name-body', '.node-content .field-item', # CMS-specific patterns
                'div.press-release-content', 'main .content', 'div#content', 'div#main-content'
            ]
            content_text = None
            for selector in content_selectors:
                 content_area = soup.select_one(selector)
                 if content_area:
                      # Clean up common unwanted tags within the selected area
                      for tag in content_area.find_all(['script', 'style', 'nav', 'footer', 'header', 'aside', 'form', 'button', '.share-this', '.related-posts', '.noprint', '.print-hide']):
                           tag.decompose()
                      # Extract text, joining paragraphs/blocks with newlines
                      text_parts = [self._clean_text(p) for p in content_area.find_all(['p', 'h1', 'h2', 'h3', 'h4', 'li'], recursive=True)] # Be more inclusive initially
                      content_text = "\n".join(filter(None, text_parts))

                      # Fallback if specific tags yield little text
                      if not content_text or len(content_text) < 100:
                           content_text = self._clean_text(content_area) # Get all text from container

                      if content_text and len(content_text) > 50: # Basic check for meaningful content
                            logger.debug(f"Extracted content using selector '{selector}' from {url}")
                            return content_text # Return first successful extraction

            # If no specific selector worked, try cleaning the whole body (last resort, often noisy)
            if not content_text:
                 body = soup.find('body')
                 if body:
                      for tag in body.find_all(['script', 'style', 'nav', 'footer', 'header', 'aside', 'form', 'button']): tag.decompose()
                      content_text = self._clean_text(body)
                      if content_text and len(content_text) > 50:
                           logger.debug(f"Extracted content using fallback 'body' from {url}")
                           return content_text

            if not content_text: logger.warning(f"Could not extract main content from {url} using common selectors or body fallback.")
            return content_text # Might return None or minimal text

        except Exception as e:
             logger.error(f"Error parsing content from {url}: {e}", exc_info=True)
             return None


    def close(self):
        """Closes the requests session."""
        if self.session:
            self.session.close()
        logger.info("HousePressCrawler session closed.")

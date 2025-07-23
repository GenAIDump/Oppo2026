# File: Oppo/data_collection/processors/campaign_website_processor.py
# Purpose: Processes crawled HTML data from campaign websites.
# Note: This is highly heuristic due to website variability. Results need validation. Sends data to MCP Server.

import logging
import os
import re
from typing import Dict, List, Any, Optional
from urllib.parse import urlparse, urljoin
from datetime import datetime, timezone # Import datetime

# Requires beautifulsoup4
try:
    from bs4 import BeautifulSoup, NavigableString, Tag
    BS4_LOADED = True
except ImportError:
     # Ensure logger is available if config import failed
     logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper(), format='%(asctime)s:%(levelname)s:%(name)s:%(lineno)d:%(message)s')
     logger = logging.getLogger(__name__)
     logger.error("BeautifulSoup4 library not found. CampaignWebsiteProcessor disabled. Install with: pip install beautifulsoup4")
     BeautifulSoup = None
     BS4_LOADED = False
     Tag = object # Dummy for type hints
     NavigableString = object # Dummy for type hints

# Import specific data models (optional, can return dicts)
try:
    # Assumes models are importable from database package relative to project root
    from database.data_models import Statement # Could also update Candidate model fields
    MODELS_LOADED = True
except ImportError:
     logging.warning("Could not import data models for CampaignWebsiteProcessor. Processing will use dicts.")
     MODELS_LOADED = False
     class Statement: pass # Dummy

# Import config if needed
try:
    from a2a_host.config import LOG_LEVEL
    CONFIG_LOADED = True
except ImportError:
     LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
     CONFIG_LOADED = False # Mark if config loading failed

# Ensure logging is configured before use
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format='%(asctime)s:%(levelname)s:%(name)s:%(lineno)d:%(message)s',
    force=True # Reconfigure if needed
)
logger = logging.getLogger(__name__)


# Define common keywords to identify page types or sections
BIO_KEYWORDS = ['about', 'meet', r'bio(?:graphy)?', 'background', 'get-to-know', 'story', 'the-candidate']
ISSUES_KEYWORDS = ['issues', 'platform', 'priorities', 'stands', 'vision', 'plan', 'policy', 'policies', 'on-the-issues', 'where-i-stand']
PRESS_KEYWORDS = ['press', 'news', 'media', 'releases', 'updates', 'statements', 'blog', 'in-the-news']
CONTACT_KEYWORDS = ['contact', 'connect', 'get-in-touch', 'office', 'locations']
DONATE_KEYWORDS = ['donate', 'contribute', 'support', 'give', 'invest', 'chip-in']

# Keywords for extracting specific bio details (examples)
EDUCATION_KEYWORDS = ['education', 'degree', 'university', 'college', 'school', 'alma-mater', 'graduate']
CAREER_KEYWORDS = ['career', 'work', 'profession', 'job', 'business', 'experience', 'service', 'military', 'professional-background']
FAMILY_KEYWORDS = ['family', 'married', 'wife', 'husband', 'children', 'son', 'daughter', 'spouse', 'personal-life']


class CampaignWebsiteProcessor:
    """
    Processes HTML content scraped from campaign websites to extract structured information.
    Relies heavily on heuristics and common web patterns. Processed data should be sent
    to the MCP Server for storage.
    """

    def __init__(self):
        """Initializes the Campaign Website processor."""
        if not BS4_LOADED:
            raise ImportError("BeautifulSoup4 is required for CampaignWebsiteProcessor but not installed.")
        logger.info("CampaignWebsiteProcessor initialized.")
        # No DB client needed; interaction should be with MCP Server API

    def _clean_text(self, element: Optional[Any]) -> Optional[str]:
        """Extracts and cleans text content from a BS4 Tag or string."""
        if not element: return None
        text = None
        try:
            if isinstance(element, NavigableString):
                 text = element.string # Use .string for NavigableString
                 if text: text = text.strip()
            elif isinstance(element, Tag):
                 # Remove common clutter before getting text
                 for clutter_tag in element.find_all(['script', 'style', 'nav', 'footer', 'header', 'button', 'form', 'figure', 'img', 'iframe', 'video', 'audio', '.noprint', '.social-links', '.share-widget', 'noscript', '.visually-hidden', '.screen-reader-text', 'svg']):
                      clutter_tag.decompose()
                 # Get text, joining with spaces, then normalize whitespace
                 text = element.get_text(separator=' ', strip=True)
            elif isinstance(element, str):
                text = element.strip()
            else:
                return None

            if text:
                 # Normalize multiple whitespace chars to single space
                 text = re.sub(r'\s+', ' ', text).strip()
                 # Optional: Further cleaning specific to campaign sites
                 text = re.sub(r'^\s*Donate Now\b', '', text, flags=re.I).strip()
                 text = re.sub(r'^\s*Sign Up\b', '', text, flags=re.I).strip()
                 text = re.sub(r'^\s*Get Involved\b', '', text, flags=re.I).strip()
                 # Remove common copyright footers if needed
                 if text.lower().startswith('©') or text.lower().startswith('copyright') or "paid for by" in text.lower(): text = None

                 return text if len(text) > 15 else None # Require minimum length for meaningful text
        except Exception as e:
             logger.debug(f"Error cleaning text from element: {e}", exc_info=False)
             return None
        return None

    def _identify_page_type(self, url: str, soup: BeautifulSoup) -> str:
        """Heuristically determines the type of page (bio, issues, press, other)."""
        url_path = urlparse(url).path.lower()
        # Normalize path segments for keyword matching (split by / or _)
        path_segments = set(filter(None, re.split(r'[/_]', url_path)))

        title = ""
        title_tag = soup.find('title')
        if title_tag: title = self._clean_text(title_tag).lower() if self._clean_text(title_tag) else ""

        h1 = ""
        h1_tag = soup.find('h1')
        if h1_tag: h1 = self._clean_text(h1_tag).lower() if self._clean_text(h1_tag) else ""

        # Check meta description too
        meta_desc = ""
        meta_tag = soup.find('meta', attrs={'name': 'description'})
        if meta_tag and meta_tag.get('content'):
             meta_desc = self._clean_text(meta_tag['content']).lower() if self._clean_text(meta_tag['content']) else ""

        # Prioritize URL path segments
        if path_segments.intersection(PRESS_KEYWORDS): return "press"
        if path_segments.intersection(ISSUES_KEYWORDS): return "issues"
        if path_segments.intersection(BIO_KEYWORDS): return "bio"
        if path_segments.intersection(CONTACT_KEYWORDS): return "contact"
        if path_segments.intersection(DONATE_KEYWORDS): return "donate"

        # Check titles/headers/meta description (using regex for word boundaries)
        combined_text = f"{title} {h1} {meta_desc}"
        if any(re.search(rf'\b{kw}\b', combined_text) for kw in PRESS_KEYWORDS): return "press"
        if any(re.search(rf'\b{kw}\b', combined_text) for kw in ISSUES_KEYWORDS): return "issues"
        if any(re.search(rf'\b{kw}\b', combined_text) for kw in BIO_KEYWORDS): return "bio"
        if any(re.search(rf'\b{kw}\b', combined_text) for kw in CONTACT_KEYWORDS): return "contact"
        if any(re.search(rf'\b{kw}\b', combined_text) for kw in DONATE_KEYWORDS): return "donate"

        logger.debug(f"Could not determine specific type for page: {url}. Type: other.")
        return "other"

    def _extract_section_tag(self, soup: BeautifulSoup, keywords: List[str]) -> Optional[Tag]:
         """Helper to find a relevant section tag based on keywords in common attributes or headers."""
         section_tag = None
         # Try common attributes first (more specific)
         for keyword in keywords:
             escaped_keyword = re.escape(keyword).replace('\\-', '[_-]?') # Allow hyphens or underscores
             # Look for IDs/classes containing the keyword (case-insensitive)
             pattern = re.compile(rf'(?:^|\b|[-_]){escaped_keyword}(?:$|\b|[-_])', re.I)
             section_tag = soup.find(['section', 'div', 'article'], id=pattern) or \
                           soup.find(['section', 'div', 'article'], class_=pattern)
             if section_tag:
                  logger.debug(f"Found section tag for '{keyword}' using attribute selector: <{section_tag.name}>")
                  return section_tag

         # If not found by attributes, try finding by header text
         if not section_tag:
              for keyword in keywords:
                   escaped_keyword = re.escape(keyword).replace('\\-', '[_-]?')
                   # Find H1-H4 whose *stripped text* matches the keyword (case-insensitive)
                   pattern = re.compile(rf'^\s*{escaped_keyword}\s*$', re.I)
                   # Search within common main content areas first to avoid matching headers in nav/footer
                   main_content = soup.select_one('main, #main, #content, .main-content, article, div[role="main"]') or soup.body
                   header = main_content.find(['h1', 'h2', 'h3', 'h4'], string=pattern) if main_content else None
                   if header:
                        # Find a reasonable parent container, preferring semantic tags, avoid going too high
                        container = header.find_parent(['article', 'section', 'div']) # Removed 'main' here
                        logger.debug(f"Found section header for '{keyword}'. Using container: <{container.name if container else 'header_itself'}>")
                        return container or header # Return container, or header itself
         logger.debug(f"No specific section tag found for keywords: {keywords}")
         return None # Not found

    def _extract_text_under_heading(self, heading_tag: Tag, max_chars=5000) -> Optional[str]:
         """Extracts paragraph/list text following a heading until the next H2/H3/H4 heading."""
         content_parts = []
         char_count = 0
         element = heading_tag.find_next_sibling()
         while element and char_count < max_chars:
             if isinstance(element, Tag):
                  # Stop if we hit the next major header
                  if element.name in ['h2', 'h3', 'h4']: break
                  # Extract text primarily from paragraphs or lists
                  text = None
                  if element.name == 'p':
                       text = self._clean_text(element)
                  elif element.name in ['ul', 'ol']:
                       items = [self._clean_text(li) for li in element.find_all('li', recursive=False)]
                       text = "; ".join(filter(None, items))

                  if text:
                       content_parts.append(text)
                       char_count += len(text)

             element = element.find_next_sibling()

         full_text = "\n".join(content_parts).strip() # Join with newlines for structure
         return full_text if full_text else None

    def _extract_issue_statements(self, soup: BeautifulSoup, page_url: str) -> List[Dict]:
        """Attempts to extract issue titles and corresponding statements."""
        issues = []
        # Find potential issue sections first using keywords
        issue_section_tag = self._extract_section_tag(soup, ISSUES_KEYWORDS)
        search_context = issue_section_tag if issue_section_tag else soup.body # Fallback to body
        if not search_context: return issues

        # Look for subheadings (h2, h3, h4 maybe strong/b) within the context
        potential_titles = search_context.find_all(['h2', 'h3', 'h4', 'strong', 'b'])
        logger.debug(f"Found {len(potential_titles)} potential issue title tags within context.")

        processed_title_tags = set() # Avoid processing nested titles multiple times

        for title_tag in potential_titles:
            if title_tag in processed_title_tags: continue

            issue_title = self._clean_text(title_tag)
            # Filter out overly short or generic titles
            if not issue_title or len(issue_title) < 5 or len(issue_title) > 100 or issue_title.lower() in ISSUES_KEYWORDS:
                 # logger.debug(f"Skipping potential issue title (short/generic): '{issue_title}'")
                 continue

            # Mark this tag and its descendants as processed for title search
            processed_title_tags.add(title_tag)
            processed_title_tags.update(title_tag.find_all(['h2','h3','h4','strong','b']))

            # Find associated text - look for paragraphs/lists immediately following
            statement_text = self._extract_text_under_heading(title_tag)

            if statement_text and len(statement_text) > 30: # Require minimum length for statement
                # Prepare structure similar to Statement model
                issue_statement = {
                    "text": statement_text,
                    "venue": f"Campaign Website - Issue: {issue_title}",
                    "source_url": page_url,
                    "statement_type": "Issue Position",
                    "topics": [issue_title] # Use extracted title as initial topic
                }
                issues.append(issue_statement)
                logger.info(f"Extracted issue statement for: '{issue_title}' from {page_url}")
            else:
                 logger.debug(f"No substantial statement text found for issue title: '{issue_title}'")

        return issues


    def process_crawled_page(self, page_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Processes a single page's data from the website crawler.

        Args:
            page_data: Dict containing 'url', 'html_content', 'title', etc.

        Returns:
            Dict representing processed data (e.g., Candidate update, list of Statements)
            or None if processing fails or page is irrelevant.
            Structure: {'candidate_update': dict|None, 'statements': list[dict]}
        """
        if not BS4_LOADED:
            logger.error("Cannot process page data: BeautifulSoup4 not loaded.")
            return None

        url = page_data.get('url')
        html_content = page_data.get('html_content') # Assumes crawler provides HTML
        if not url or not html_content:
             logger.warning("Skipping processing: Missing URL or HTML content.")
             return None

        logger.info(f"Processing campaign page: {url}")
        output = {
            'candidate_update': None, # Dict to update Candidate node
            'statements': []         # List of Statement dicts
        }

        try:
            soup = BeautifulSoup(html_content, 'html.parser')

            # --- Page Type Identification ---
            page_type = self._identify_page_type(url, soup)
            logger.debug(f"Identified page type: {page_type}")

            # --- Extract Candidate Name Heuristic ---
            candidate_name_mention = None
            page_title = self._clean_text(soup.find('title'))
            h1_text = self._clean_text(soup.find('h1'))
            # Try to find a pattern like "Name | Campaign Site" or "Meet Name"
            if page_title:
                name_match = re.match(r"^([A-Z][a-z']+\s+(?:[A-Z][a-z']+\s+)?(?:[A-Z]\.\s+)?[A-Z][a-zA-Z']+)", page_title.replace("Meet ",""))
                if name_match: candidate_name_mention = name_match.group(1).strip()
            if not candidate_name_mention and h1_text:
                 name_match_h1 = re.search(r"^([A-Z][a-z']+\s+(?:[A-Z][a-z']+\s+)?(?:[A-Z]\.\s+)?[A-Z][a-zA-Z']+)", h1_text)
                 if name_match_h1: candidate_name_mention = name_match_h1.group(1).strip()

            # --- Extract Data Based on Page Type ---
            if page_type == 'bio':
                # Extract full bio section first
                bio_heading = self._extract_section_tag(soup, BIO_KEYWORDS)
                bio_text = self._extract_text_under_heading(bio_heading) if bio_heading else None
                # Fallback to just grabbing main content if no specific section found
                if not bio_text:
                     main_content_tag = soup.select_one('main, article, #main, .main-content') or soup.body
                     if main_content_tag: bio_text = self._clean_text(main_content_tag)

                if bio_text:
                    output['statements'].append({
                        "text": bio_text,
                        "venue": "Campaign Website - Bio Page", "source_url": url,
                        "statement_type": "Biography", "topics": ["Biography"]
                    })
                    logger.info(f"Extracted Bio content from {url}")

                # Prepare potential candidate update fields from bio sub-sections
                edu_text = self._extract_text_under_heading(self._find_section_heading(soup, EDUCATION_KEYWORDS) or bio_heading) if bio_heading else None
                career_text = self._extract_text_under_heading(self._find_section_heading(soup, CAREER_KEYWORDS) or bio_heading) if bio_heading else None
                family_text = self._extract_text_under_heading(self._find_section_heading(soup, FAMILY_KEYWORDS) or bio_heading) if bio_heading else None

                candidate_update = {"candidate_name": candidate_name_mention} # Start with name
                if edu_text: candidate_update['education_summary'] = edu_text[:1000] # Truncate
                if career_text: candidate_update['career_summary'] = career_text[:1000]
                if family_text: candidate_update['family_summary'] = family_text[:1000]
                output['candidate_update'] = {k:v for k,v in candidate_update.items() if v} # Filter None

            elif page_type == 'issues':
                 issue_statements = self._extract_issue_statements(soup, url)
                 output['statements'].extend(issue_statements)

            elif page_type == 'press':
                 # Extract links to press releases as simple statements
                 press_section = self._extract_section_tag(soup, PRESS_KEYWORDS) or soup.body
                 if press_section:
                     for item in press_section.find_all(['li', 'div', 'article', 'a'], limit=25): # Limit items processed
                          link_tag = item if item.name == 'a' else item.find('a', href=True)
                          if not link_tag: continue
                          href = link_tag.get('href')
                          title = self._clean_text(link_tag) or self._clean_text(item.find(['h3','h4']))
                          if href and title and not href.startswith(('#', 'javascript:')):
                              full_url = urljoin(url, href)
                              # Basic check if it's likely an internal link (vs. external media)
                              if urlparse(full_url).netloc == urlparse(url).netloc:
                                   output['statements'].append({
                                        "text": f"Press Release Mentioned: {title}",
                                        "venue": "Campaign Website - Press Section",
                                        "source_url": full_url, # Link to actual release on site
                                        "statement_type": "Press Release Link",
                                   })
                 logger.info(f"Extracted {len(output['statements'])} press links from {url}")


            # --- Generic Processing ---
            # If no specific type matched, could still extract H2 + P as statements
            if page_type == 'other' and not output['statements']:
                 logger.debug(f"Attempting generic H2/P extraction for 'other' page: {url}")
                 output['statements'].extend(self._extract_issue_statements(soup, url)) # Reuse issue logic for generic headings


            # --- Finalize ---
            # Filter empty results
            if not output['candidate_update'] and not output['statements']:
                 logger.info(f"No specific data extracted from page: {url}")
                 return None # Return None if nothing useful found

            # Add candidate name mention to all statements if found
            if candidate_name_mention and output['statements']:
                 for stmt in output['statements']:
                      # Avoid overwriting if processor found a more specific name
                      if not stmt.get('member_name_extracted'):
                           stmt['member_name_extracted'] = candidate_name_mention
            # Add timestamp of processing
            output['processed_timestamp_utc'] = datetime.now(timezone.utc).isoformat()

            # NOTE: The caller (e.g., background job) needs to take this 'output' dict
            # and interact with the MCP Server API.
            # It needs to determine the target candidate_id (using candidate_name_mention, domain name, etc.)
            # then send the candidate_update dict (if any) to POST /candidate
            # and send each dict in the statements list to POST /statement (or equivalent).

            logger.info(f"Processed campaign page {url} ({page_type}). Found {len(output['statements'])} statement(s). Candidate mention: {candidate_name_mention}")
            return output

        except Exception as e:
            logger.error(f"Error processing campaign page {url}: {e}", exc_info=True)
            return None

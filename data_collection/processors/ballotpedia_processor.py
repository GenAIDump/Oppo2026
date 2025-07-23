# File: Oppo/data_collection/processors/ballotpedia_processor.py
# Purpose: Processes scraped HTML from Ballotpedia pages.
# Note: Relies heavily on Ballotpedia's specific HTML structure, which changes often.
# Selectors need regular review and updates. Sends data to MCP server.

import logging
import os
import re
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime, date, timezone

# Requires beautifulsoup4
try:
    from bs4 import BeautifulSoup, NavigableString, Tag
    BS4_LOADED = True
except ImportError:
     # Ensure logger is available if config import failed
     logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper(), format='%(asctime)s:%(levelname)s:%(name)s:%(lineno)d:%(message)s')
     logger = logging.getLogger(__name__)
     logger.error("BeautifulSoup4 library not found. BallotpediaProcessor disabled. Install with: pip install beautifulsoup4")
     BeautifulSoup = None
     BS4_LOADED = False
     Tag = object # Dummy for type hints
     NavigableString = object # Dummy for type hints


# Import specific data models (optional, can return dicts)
try:
    # Assumes models are importable from database package relative to project root
    from database.data_models import Candidate, Statement
    MODELS_LOADED = True
except ImportError:
     logging.warning("Could not import data models for BallotpediaProcessor. Processing will use dicts.")
     MODELS_LOADED = False
     class Candidate: pass # Dummy
     class Statement: pass # Dummy

# Import config if needed
try:
    from a2a_host.config import LOG_LEVEL
    CONFIG_LOADED = True
except ImportError:
     LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
     CONFIG_LOADED = False

# Ensure logging is configured before use
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format='%(asctime)s:%(levelname)s:%(name)s:%(lineno)d:%(message)s',
    force=True # Reconfigure if needed
)
logger = logging.getLogger(__name__)


class BallotpediaProcessor:
    """
    Processes HTML content scraped from Ballotpedia pages to extract structured data
    about candidates, elections, positions, etc.
    WARNING: Highly dependent on Ballotpedia's specific HTML structure and CSS classes.
    """

    def __init__(self):
        """Initializes the Ballotpedia processor."""
        if not BS4_LOADED:
            raise ImportError("BeautifulSoup4 is required for BallotpediaProcessor but not installed.")
        logger.info("BallotpediaProcessor initialized.")
        # No DB client needed if using MCP architecture

    def _clean_text(self, element: Optional[Any]) -> Optional[str]:
        """Extracts and cleans text content from a BS4 Tag or string."""
        if not element: return None
        text = None
        try:
            if isinstance(element, NavigableString):
                 text = element.string # Use .string for NavigableString
                 if text: text = text.strip()
            elif isinstance(element, Tag):
                 # Remove common Ballotpedia clutter like "[show]", "[hide]", edit links, citations
                 for clutter_tag in element.find_all(['span', 'sup'], class_=re.compile(r'mw-editsection|reference|noprint', re.I)):
                      clutter_tag.decompose()
                 # Remove hidden elements often used for screen readers
                 for hidden_tag in element.find_all(class_=re.compile(r'hidden|sr-only|screen-reader-text', re.I)):
                      hidden_tag.decompose()

                 text = element.get_text(separator=' ', strip=True)
                 text = text.replace('[hide]', '').replace('[show]', '')
                 # Remove citation needed tags more robustly
                 text = re.sub(r'\[\s*citation needed\s*\]', '', text, flags=re.I)
            elif isinstance(element, str):
                text = element.strip()
            else:
                return None

            if text:
                 # Normalize whitespace
                 text = re.sub(r'\s+', ' ', text).strip()
                 # Remove leading/trailing list bullets if they remain
                 text = re.sub(r'^\*+\s*', '', text).strip()
                 return text if len(text) > 1 else None # Return None for very short remnants
        except Exception as e:
             logger.debug(f"Error cleaning text from element: {e}", exc_info=False)
             return None
        return None

    def _extract_state_from_district(self, district: Optional[str]) -> Optional[str]:
         """Extracts 2-letter state code from district string (e.g., PA-01 -> PA, California District 10 -> CA)."""
         if not district or not isinstance(district, str): return None
         district_upper = district.strip().upper()
         # Pattern 1: XX-YY or XX-L
         match1 = re.match(r"([A-Z]{2})[-_ ]?(\d+|L)", district_upper)
         if match1: return match1.group(1)
         # Pattern 2: State Name District YY
         # Requires a mapping from state name to code
         state_names = {
             "ALABAMA": "AL", "ALASKA": "AK", "ARIZONA": "AZ", "ARKANSAS": "AR", "CALIFORNIA": "CA",
             "COLORADO": "CO", "CONNECTICUT": "CT", "DELAWARE": "DE", "FLORIDA": "FL", "GEORGIA": "GA",
             "HAWAII": "HI", "IDAHO": "ID", "ILLINOIS": "IL", "INDIANA": "IN", "IOWA": "IA", "KANSAS": "KS",
             "KENTUCKY": "KY", "LOUISIANA": "LA", "MAINE": "ME", "MARYLAND": "MD", "MASSACHUSETTS": "MA",
             "MICHIGAN": "MI", "MINNESOTA": "MN", "MISSISSIPPI": "MS", "MISSOURI": "MO", "MONTANA": "MT",
             "NEBRASKA": "NE", "NEVADA": "NV", "NEW HAMPSHIRE": "NH", "NEW JERSEY": "NJ", "NEW MEXICO": "NM",
             "NEW YORK": "NY", "NORTH CAROLINA": "NC", "NORTH DAKOTA": "ND", "OHIO": "OH", "OKLAHOMA": "OK",
             "OREGON": "OR", "PENNSYLVANIA": "PA", "RHODE ISLAND": "RI", "SOUTH CAROLINA": "SC",
             "SOUTH DAKOTA": "SD", "TENNESSEE": "TN", "TEXAS": "TX", "UTAH": "UT", "VERMONT": "VT",
             "VIRGINIA": "VA", "WASHINGTON": "WA", "WEST VIRGINIA": "WV", "WISCONSIN": "WI", "WYOMING": "WY",
             # Add territories if needed
             "DISTRICT OF COLUMBIA": "DC"
         }
         for name, code in state_names.items():
             if district_upper.startswith(name):
                  return code
         # Fallback: Check if string itself is a state code
         if len(district_upper) == 2 and district_upper.isalpha(): return district_upper
         return None


    def _parse_infobox(self, soup: BeautifulSoup) -> Dict[str, Any]:
        """Parses the main infobox table for key candidate/election details."""
        infobox_data = {}
        # Look for standard infobox person, fallback to general infobox
        infobox = soup.find('table', class_=lambda x: x and 'infobox' in x and 'person' in x) or \
                  soup.find('table', class_='infobox')

        if not infobox:
            logger.debug("No infobox table found on page.")
            return infobox_data

        logger.debug("Processing infobox table...")
        # Candidate Name
        caption_tag = infobox.find('caption')
        name_tags = [caption_tag] if caption_tag else []
        name_tags.extend(infobox.select('th.infobox-header, th.infobox-title, .infobox-header')) # Common header classes/tags
        for tag in name_tags:
             name = self._clean_text(tag)
             if name:
                  infobox_data['infobox_name'] = name
                  break # Take the first good name found

        rows = infobox.find_all('tr', recursive=False) # Only direct children rows
        for row in rows:
             # Find header (th or td with label class) and data (td)
             header_tag = row.find(['th', 'td'], class_='infobox-label', recursive=False)
             data_tag = row.find('td', recursive=False) # Find first td sibling/child
             if not header_tag: header_tag = row.find('th', recursive=False)
             # Sometimes data is in the same row but not sibling, check within row if needed
             if header_tag and not data_tag: data_tag = header_tag.find_next_sibling('td')
             # Basic th/td pair structure
             if not header_tag or not data_tag:
                   cells = row.find_all(['th', 'td'], recursive=False)
                   if len(cells) == 2 and cells[0].name == 'th':
                       header_tag, data_tag = cells[0], cells[1]

             if header_tag and data_tag:
                 header_text = self._clean_text(header_tag).lower().replace(':', '').strip()
                 # Get text, potentially joining list items etc.
                 data_text = self._clean_text(data_tag) or " ".join(filter(None, [self._clean_text(li) for li in data_tag.find_all('li')]))

                 if not header_text or not data_text: continue

                 logger.debug(f"Infobox Row - Header: '{header_text}', Data: '{data_text[:50]}...'")
                 # Map common headers to standardized keys
                 if 'name' in header_text and 'infobox_name' not in infobox_data: infobox_data['infobox_name'] = data_text
                 elif 'party affiliation' in header_text or header_text == 'party': infobox_data['political_party'] = data_text.split('(')[0].strip()
                 elif 'office sought' in header_text or header_text == 'office' or 'running for' in header_text: infobox_data['office_sought'] = data_text
                 elif header_text == 'district': infobox_data['district_infobox'] = data_text
                 elif header_text == 'state': infobox_data['state_infobox'] = data_text
                 elif 'election date' in header_text or header_text == 'election': infobox_data['election_details'] = f"{infobox_data.get('election_details', '')} | {data_text}".strip(' |')
                 elif 'campaign website' in header_text or header_text == 'website':
                      link = data_tag.find('a', href=True)
                      infobox_data['website_campaign'] = link['href'] if link else data_text
                 elif 'twitter' in header_text or 'x (twitter)' in header_text:
                      link = data_tag.find('a', href=True)
                      infobox_data['x_handle_url'] = link['href'] if link else data_text
                 elif 'facebook' in header_text:
                      link = data_tag.find('a', href=True)
                      infobox_data['facebook_url'] = link['href'] if link else data_text
                 elif 'birth date' in header_text: infobox_data['birth_date_str'] = data_text
                 elif 'education' in header_text: infobox_data['education_infobox'] = data_text
                 elif 'occupation' in header_text or 'career' in header_text: infobox_data['occupation_infobox'] = data_text

        logger.debug(f"Parsed infobox data: {infobox_data}")
        return infobox_data

    def _find_section_heading(self, soup: BeautifulSoup, keywords: List[str]) -> Optional[Tag]:
         """Finds H2/H3 heading tag matching keywords, preferring IDs."""
         for keyword in keywords:
              section_id = keyword.replace(' ', '_')
              header = soup.find(id=re.compile(rf'^{re.escape(section_id)}$', re.I))
              if header:
                   logger.debug(f"Found section heading by ID for '{keyword}': <{header.name} id='{header.get('id')}'>")
                   return header
         # Fallback to matching text content
         for keyword in keywords:
              # Match exact phrase or keyword variations
              pattern_text = rf'^\s*{re.escape(keyword)}\s*$'
              pattern = re.compile(pattern_text, re.I)
              # Look for span inside header commonly used by Ballotpedia
              header = soup.find(['h2','h3'], string=pattern) or \
                       soup.find(lambda tag: tag.name in ['h2','h3'] and tag.find('span', string=pattern, recursive=False))
              if header:
                   logger.debug(f"Found section heading by text for '{keyword}': <{header.name}>")
                   return header
         logger.debug(f"Section heading not found for keywords: {keywords}")
         return None

    def _extract_text_under_heading(self, heading_tag: Tag, max_chars=5000) -> Optional[str]:
         """Extracts paragraph/list text following a heading until the next H2/H3 heading."""
         content_parts = []
         char_count = 0
         element = heading_tag.find_next_sibling()
         while element and char_count < max_chars:
             if isinstance(element, Tag):
                  if element.name in ['h2', 'h3']: break # Stop at next major header
                  text = None
                  if element.name == 'p':
                       text = self._clean_text(element)
                  elif element.name in ['ul', 'ol']:
                       items = [self._clean_text(li) for li in element.find_all('li', recursive=False)]
                       text = "; ".join(filter(None, items))
                  elif element.name == 'dl': # Handle definition lists if used for positions
                       items = [f"{self._clean_text(dt)}: {self._clean_text(dd)}"
                                for dt, dd in zip(element.find_all('dt'), element.find_all('dd'))
                                if self._clean_text(dt) and self._clean_text(dd)]
                       text = "; ".join(items)

                  if text:
                       content_parts.append(text)
                       char_count += len(text)
             # else: # Include text nodes?
             #      cleaned_nav = self._clean_text(element)
             #      if cleaned_nav and len(cleaned_nav) > 10: content_parts.append(cleaned_nav)
             element = element.find_next_sibling()

         full_text = "\n".join(content_parts).strip() # Join with newlines
         return full_text if len(full_text) > 10 else None


    def process_ballotpedia_page(self, url: str, html_content: str) -> Optional[Dict]:
        """
        Processes the HTML content of a Ballotpedia candidate page.

        Args:
            url: The URL of the scraped page.
            html_content: The raw HTML content.

        Returns:
            Dict: Structured data {'candidate_data': dict, 'statement_data': list} or None.
        """
        if not BS4_LOADED or not html_content:
            logger.error("Cannot process Ballotpedia page: BeautifulSoup4 not loaded or no HTML content.")
            return None

        logger.info(f"Processing Ballotpedia page: {url}")
        try:
            soup = BeautifulSoup(html_content, 'html.parser')

            # --- Infobox Data ---
            infobox = self._parse_infobox(soup)

            # --- Candidate Name ---
            page_title_h1 = soup.find('h1', id='firstHeading')
            page_title = self._clean_text(page_title_h1) if page_title_h1 else None
            candidate_name = infobox.get('infobox_name', page_title) or "Unknown Candidate"
            candidate_name = re.sub(r'\s+\(\d{4}\)$', '', candidate_name).strip()
            candidate_name = re.sub(r'\s+(?:general|primary)\s+election$', '', candidate_name, flags=re.I).strip()
            candidate_name = re.sub(r'\s+campaigns$', '', candidate_name, flags=re.I).strip() # Remove "campaigns" suffix

            # --- District/State ---
            state = infobox.get('state_infobox')
            district_raw = infobox.get('district_infobox')
            district_std = None
            # Try extracting state from district string first
            if not state and district_raw: state = self._extract_state_from_district(district_raw)
            # Use state from infobox if extraction failed
            if not state and infobox.get('state_infobox'): state = self._extract_state_from_district(infobox.get('state_infobox'))
            # Format district
            if state and district_raw: district_std = self.format_district(state, district_raw)

            # --- Biography ---
            bio_heading = self._find_section_heading(soup, ['Biography', 'Career', 'Background', 'Personal life', 'Early life and education'])
            bio_text = self._extract_text_under_heading(bio_heading) if bio_heading else None

            # --- Campaign Themes / Positions ---
            themes_heading = self._find_section_heading(soup, ['Campaign themes', 'Political positions', 'Policy positions', 'Issues', 'Platform'])
            themes_text = self._extract_text_under_heading(themes_heading) if themes_heading else None
            statements = []
            if themes_text:
                 potential_statements = [p for p in themes_text.split('\n') if p.strip()] # Split by newline used in helper
                 for stmt_text in potential_statements:
                      cleaned = stmt_text.strip()
                      if len(cleaned) > 40: # Filter short fragments
                           statements.append({
                                "text": cleaned,
                                "venue": "Ballotpedia Campaign Themes/Positions",
                                "source_url": url,
                                "statement_type": "Position Statement",
                                # Add date? Usually not available for these sections
                           })
            logger.info(f"Extracted {len(statements)} potential statements from Ballotpedia page.")

            # --- Prepare Candidate Payload for MCP ---
            candidate_payload = {
                "candidate_id": self.generate_candidate_id(candidate_name, district_std),
                "name": candidate_name,
                "party": self._standardize_party(infobox.get('political_party')),
                "state": state,
                "district": district_std,
                "office_sought": infobox.get('office_sought') or infobox.get('election_details'),
                "campaign_website": infobox.get('website_campaign'),
                "ballotpedia_url": url,
                "biography_summary": bio_text[:2000] if bio_text else None, # Truncate
                "x_handle_url": infobox.get('x_handle_url'),
                "facebook_url": infobox.get('facebook_url'),
                "source": "Ballotpedia",
            }
            candidate_payload = {k: v for k, v in candidate_payload.items() if v is not None}

            # Add candidate_id to extracted statements
            if candidate_payload.get('candidate_id'):
                 for stmt in statements:
                      stmt['candidate_id'] = candidate_payload['candidate_id']
            else:
                 logger.warning(f"No candidate ID generated for {candidate_name} at {url}, statements cannot be linked.")
                 statements = [] # Clear statements

            # Final structure to return
            final_data = {
                 "candidate_data": candidate_payload, # Data for Candidate node
                 "statement_data": statements, # List of statements to potentially add
                 "processed_timestamp_utc": datetime.now(timezone.utc).isoformat()
            }

            logger.info(f"Successfully processed Ballotpedia page: {url} for '{candidate_name}'")
            return final_data

        except Exception as e:
            logger.error(f"Error processing Ballotpedia page {url}: {e}", exc_info=True)
            return None

    # --- Helper methods ---
    def _standardize_party(self, party_code: Optional[str]) -> Optional[str]:
        if not party_code or not isinstance(party_code, str): return None
        p = party_code.split('/')[0].split('(')[0].strip().upper()
        if p in ['REPUBLICAN', 'R', 'REP']: return 'GOP'
        if p in ['DEMOCRAT', 'DEMOCRATIC', 'D', 'DEM']: return 'DEM'
        if p in ['INDEPENDENT', 'IND', 'I', 'NONPARTISAN', 'UNAFFILIATED', 'NO PARTY AFFILIATION', 'UN', 'NP']: return 'IND'
        if p in ['LIBERTARIAN', 'LBT', 'LPN', 'L']: return 'LIB'
        if p in ['GREEN', 'GRN', 'G']: return 'GRN'
        logger.debug(f"Unknown party encountered on Ballotpedia: {party_code} -> {p}")
        return p # Return cleaned original if no match

    def format_district(self, state: Optional[str], district_num_or_l: Optional[Any]) -> Optional[str]:
         if not state or district_num_or_l is None: return None
         state = state.upper()
         district_str = str(district_num_or_l).strip().upper().replace('AT-LARGE','L').replace('AT LARGE','L')
         if district_str in ['L', '0', '00']: return f"{state}-L"
         elif district_str.isdigit(): return f"{state}-{int(district_str):02d}"
         else:
             if f"{state}-" in district_str: return district_str
             logger.warning(f"Could not format district number '{district_num_or_l}' for state '{state}'.")
             return None

    def generate_candidate_id(self, name: Optional[str], district: Optional[str]) -> Optional[str]:
         if not name or not district: return None
         name_part = re.sub(r'\W+', '', name).lower()
         dist_part = re.sub(r'\W+', '', district).lower()
         return f"cand_{name_part}_{dist_part}"[:64]

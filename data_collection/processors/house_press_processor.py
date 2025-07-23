# File: Oppo/data_collection/processors/house_press_processor.py
# Purpose: Processes raw House Press Release data (titles, links, dates, potentially content).
# Note: In MCP architecture, formats data for AddStatement requests to MCP Server.

import logging
import os
from datetime import datetime, date, timezone
from typing import Dict, List, Any, Optional
import re

# Import specific data models
try:
    # Assuming Statement model can represent a press release summary or key quote
    from database.data_models import Statement
    MODELS_LOADED = True
except ImportError:
     # Ensure logger is available if config import failed
     logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper(), format='%(asctime)s:%(levelname)s:%(name)s:%(lineno)d:%(message)s')
     logger = logging.getLogger(__name__)
     logger.error("Could not import data models for HousePressProcessor. Processing will use dicts.")
     MODELS_LOADED = False
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

# Optional NLP libraries (if doing topic/sentiment here)
# try:
#     import spacy
#     NLP = spacy.load("en_core_web_sm")
# except ImportError:
#     logger.warning("SpaCy not installed. Advanced NLP processing disabled in HousePressProcessor.")
#     NLP = None


class HousePressProcessor:
    """
    Processes raw data scraped from House Republican press release sources.
    Extracts key info and formats it, ideally for ingestion via MCP Server.
    """

    def __init__(self):
        """Initializes the House Press processor."""
        logger.info("HousePressProcessor initialized.")
        # No DB client needed if using MCP architecture

    def _parse_iso_date(self, date_string: Optional[str]) -> Optional[date]:
        """Safely parses ISO date strings (YYYY-MM-DD or full ISO with T/Z)."""
        if not date_string: return None
        try:
             # Handle both date and datetime ISO strings
             dt = datetime.fromisoformat(date_string.replace('Z', '+00:00'))
             return dt.date() # Return only the date part
        except (ValueError, TypeError):
             logger.debug(f"Could not parse ISO date string: {date_string}")
             return None

    def _extract_member_name(self, title: str, source_name: str) -> Optional[str]:
        """Placeholder: Extracts member name from title or source info."""
        # Try finding "Rep./Congressman/Congresswoman Name" in title
        # Pattern allows for middle initials/names and common suffixes like Jr.
        match = re.search(
            r"\b(?:Rep\.|Representative|Congressman|Congresswoman)\s+([A-Z][a-zA-Z.'\- ]+(?:\s+(?:Jr\.|Sr\.|I{1,3}))?)\b",
            title, re.I
            )
        if match:
            name = re.sub(r"\s+'s\b", "", match.group(1).strip()) # Clean possessive
            # Basic check for likely name structure
            if len(name.split()) >= 2:
                logger.debug(f"Extracted name '{name}' from title: '{title[:50]}...'")
                return name

        # Fallback: Extract from source_name if it follows pattern "Rep Committee (member name)"
        match_source = re.match(r"Rep Committee \((.+)\)", source_name, re.I)
        if match_source:
             name = match_source.group(1).strip()
             logger.debug(f"Extracted name '{name}' from source: '{source_name}'")
             return name

        logger.debug(f"Could not extract member name from title: '{title}' or source: '{source_name}'")
        return None # Requires more robust matching or external linking logic


    def process_release(self, release_data: Dict[str, Any]) -> Optional[Dict]:
        """
        Processes a single raw press release record fetched by the crawler.
        Formats data suitable for creating a Statement node via MCP.

        Args:
            release_data (Dict): Dict from crawler (e.g., {'title':..., 'url':..., 'parsed_date_utc':..., 'source_name':..., 'content':...})

        Returns:
            Optional[Dict]: Processed data dict (Statement-like structure) or None.
        """
        required_fields = ['url', 'title', 'source_name']
        if not all(release_data.get(field) for field in required_fields):
             logger.warning(f"Skipping press release due to missing required fields: {release_data.get('url') or 'No URL'}")
             return None

        try:
            title = release_data.get('title', '').strip()
            url = release_data.get('url')
            source = release_data.get('source_name')
            parsed_date = self._parse_iso_date(release_data.get('parsed_date_utc'))
            full_content = release_data.get('full_content') # Assume crawler might provide this

            # Extract member name
            member_name = self._extract_member_name(title, source)

            # Generate summary if full content available
            content_summary = None
            if full_content:
                 summary = full_content[:500].strip() # Simple truncation
                 if len(full_content) > 500: summary += "..."
                 content_summary = summary
            else:
                 content_summary = title # Fallback to title if no content

            # --- Prepare Statement Payload ---
            # The 'candidate_id' needs to be resolved externally (e.g., by MCP server)
            # based on the extracted member_name or other context.
            statement_payload = {
                 # "candidate_id": None, # To be resolved by MCP/caller
                 "member_name_extracted": member_name, # Hint for resolution
                 "text": content_summary or title, # Use summary or title
                 "full_text_available": bool(full_content), # Flag if full content was processed
                 "date": parsed_date.isoformat() if parsed_date else None,
                 "venue": source,
                 "source_url": url,
                 "statement_type": "Press Release",
                 "source": "House Press Release",
                 # Optional: Add topics extracted via NLP if implemented here
                 # "topics": self._extract_topics(full_content or title),
            }

            # Use Pydantic model for validation if available and return dict
            if MODELS_LOADED:
                 try:
                      # Map fields carefully if model names differ
                      mapped_payload = statement_payload.copy() # Avoid modifying original dict
                      # Example mapping if needed: mapped_payload['statement_text'] = mapped_payload.pop('text')
                      validated_data = Statement(**mapped_payload).model_dump(exclude_none=True)
                      return validated_data
                 except Exception as pydantic_error:
                      logger.error(f"Pydantic validation failed for press release {url}: {pydantic_error}")
                      return None
            else:
                 return {k: v for k, v in statement_payload.items() if v is not None}

        except Exception as e:
            logger.error(f"Error processing press release data: {release_data.get('url')} - {e}", exc_info=True)
            return None

    def process_releases(self, raw_release_list: List[Dict[str, Any]]) -> List[Dict]:
        """Processes a list of raw press release records."""
        logger.info(f"Processing {len(raw_release_list)} raw House press release records...")
        processed_list = []
        for raw_data in raw_release_list:
            processed = self.process_release(raw_data)
            if processed:
                processed_list.append(processed)
        logger.info(f"Successfully processed {len(processed_list)} House press release records.")
        # NOTE: The caller (e.g., triggered background job) should send this list
        # item by item to the appropriate MCP Server endpoint (e.g., POST /statement).
        return processed_list

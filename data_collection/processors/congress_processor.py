# File: Oppo/data_collection/processors/congress_processor.py
# Purpose: Processes raw Congress.gov API data into standardized Data Models.
# Note: In MCP architecture, this processor would format data and send
# structured requests (e.g., AddVote, UpdateBill) to the MCP Server API.

import logging
import os
from datetime import datetime, date, timezone
from typing import Dict, List, Any, Optional
import re

# Import specific data models
try:
    from database.data_models import Candidate, Vote, Bill # Add Committee, CommitteeMembership if processing those
except ImportError:
     logging.error("Could not import data models for CongressProcessor. Processing will use dicts.")
     class Candidate: pass
     class Vote: pass
     class Bill: pass

# Import config if needed
try:
    from a2a_host.config import LOG_LEVEL
except ImportError:
     LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format='%(asctime)s:%(levelname)s:%(name)s:%(message)s'
)
logger = logging.getLogger(__name__)


class CongressProcessor:
    """
    Processes raw data fetched from the Congress.gov API into structured formats
    ready for storage (ideally via MCP Server).
    """

    def __init__(self):
        """Initializes the Congress processor."""
        logger.info("CongressProcessor initialized.")
        # No direct DB client needed if using MCP architecture

    def _parse_congress_date(self, date_string: Optional[str]) -> Optional[date]:
        """Safely parses YYYY-MM-DD date strings from Congress API."""
        if not date_string:
            return None
        try:
            # Congress API typically uses YYYY-MM-DD
            return datetime.strptime(date_string, '%Y-%m-%d').date()
        except (ValueError, TypeError):
            logger.debug(f"Could not parse Congress date string: {date_string}")
            return None

    def _parse_congress_datetime(self, datetime_string: Optional[str]) -> Optional[datetime]:
        """Safely parses ISO 8601 datetime strings (potentially with 'Z') from Congress API."""
        if not datetime_string:
            return None
        try:
            # Handle 'Z' for UTC
            dt = datetime.fromisoformat(datetime_string.replace('Z', '+00:00'))
            # Ensure timezone is UTC if parsed as naive
            if dt.tzinfo is None:
                 dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except (ValueError, TypeError):
            logger.debug(f"Could not parse Congress datetime string: {datetime_string}")
            return None

    def _extract_district(self, member_data: Dict) -> Optional[str]:
        """Extracts and standardizes district information."""
        terms = member_data.get('terms', [])
        if not terms: return None
        latest_term = terms[-1] # Assume last term is the most relevant/current
        state = latest_term.get('stateCode')
        district_num = latest_term.get('district')
        if state and district_num is not None: # District can be 0 for At-Large
             # Format as STATE-DISTRICT (e.g., CA-10, SD-L)
             dist_str = "L" if district_num == 0 else f"{district_num:02d}"
             return f"{state}-{dist_str}"
        return None

    def _extract_latest_term_info(self, member_data: Dict) -> Dict:
        """Extracts info from the latest term listed."""
        term_info = {}
        terms = member_data.get('terms', [])
        if terms:
             latest = terms[-1]
             term_info['term_congress'] = latest.get('congress')
             term_info['term_chamber'] = latest.get('chamber')
             term_info['term_start_date'] = self._parse_congress_date(latest.get('startYear')) # API might use startYear? check docs
             term_info['term_end_date'] = self._parse_congress_date(latest.get('endYear'))
             term_info['term_state'] = latest.get('stateCode')
             term_info['term_district_num'] = latest.get('district')
             term_info['term_party'] = latest.get('partyName') # Usually full name
        return term_info


    def process_member(self, member_data: Dict[str, Any]) -> Optional[Dict]:
        """Processes a single raw member record from Congress API."""
        try:
            bioguide_id = member_data.get('bioguideId')
            if not bioguide_id:
                 logger.warning("Skipping member record due to missing bioguideId.")
                 return None

            latest_term = self._extract_latest_term_info(member_data)
            district_standard = self._extract_district(member_data)

            processed = {
                "bioguide_id": bioguide_id,
                # Use direct 'name' if available, otherwise construct
                "name": member_data.get('directOrderName', f"{member_data.get('firstName', '')} {member_data.get('lastName', '')}".strip()),
                "first_name": member_data.get('firstName'),
                "last_name": member_data.get('lastName'),
                # Get party from latest term if possible
                "party": latest_term.get('term_party', member_data.get('partyHistory', [{}])[-1].get('partyName')),
                "state": latest_term.get('term_state'),
                "district": district_standard, # Standardized district
                "chamber": latest_term.get('term_chamber'),
                "congress_gov_url": member_data.get('url'), # URL to Congress.gov profile
                "source": "Congress.gov API",
                # Add more fields: birthDate, sponsoredLegislation.count, cosponsoredLegislation.count etc.
                "birth_date": self._parse_congress_date(member_data.get('birthDate')),
                "sponsored_count": member_data.get('sponsoredLegislation', {}).get('count'),
                "cosponsored_count": member_data.get('cosponsoredLegislation', {}).get('count'),
            }
            # Use Pydantic model for validation if available
            # return Candidate(**processed).model_dump(exclude_none=True) # Map Congress fields to Candidate model
            return {k: v for k, v in processed.items() if v is not None}
        except Exception as e:
            logger.error(f"Error processing Congress member data: {member_data.get('bioguideId')} - {e}", exc_info=True)
            return None

    def process_members(self, raw_member_list: List[Dict[str, Any]]) -> List[Dict]:
        """Processes a list of raw member records."""
        logger.info(f"Processing {len(raw_member_list)} raw Congress member records...")
        processed_list = []
        for raw_data in raw_member_list:
            processed = self.process_member(raw_data)
            if processed:
                processed_list.append(processed)
        logger.info(f"Successfully processed {len(processed_list)} Congress member records.")
        return processed_list


    def process_vote(self, vote_data: Dict[str, Any], member_bioguide_id: Optional[str] = None) -> Optional[Dict]:
        """Processes a single raw vote record from Congress API."""
        # Vote data structure from API can vary depending on endpoint (member votes vs roll call votes)
        # This assumes structure from member votes endpoint: List[{ "member": {...}, "vote": {...}, "position": "..."}]
        # OR structure from /vote endpoint: { "vote": {...} } - needs adaptation based on source
        try:
            vote_details = vote_data.get('vote', {})
            if not vote_details:
                logger.warning(f"Skipping vote record: Missing 'vote' details dict. Data: {vote_data}")
                return None

            # Extract identifiers (handle potential nesting)
            congress = vote_details.get('congress')
            session = vote_details.get('session')
            chamber = vote_details.get('chamber')
            roll_call = vote_details.get('rollCallNumber')
            if not all([congress, session, chamber, roll_call]):
                 logger.warning(f"Skipping vote record: Missing key identifiers (congress, session, chamber, rollCallNumber). Data: {vote_details}")
                 return None

            # Construct a unique ID for the vote event itself
            vote_event_id = f"{congress}-{chamber}-{session}-{roll_call}"
            # Get related bill info if present
            bill_info = vote_details.get('bill')
            bill_id = f"{congress}-{bill_info['type'].lower()}-{bill_info['number']}" if bill_info and bill_info.get('type') and bill_info.get('number') else None

            processed = {
                # Use member_bioguide_id if passed (from member votes endpoint)
                "bioguide_id": member_bioguide_id or vote_data.get('member', {}).get('bioguideId'),
                "position": vote_data.get('position'), # Member's position (Yea, Nay, etc.)
                # Vote Event Details
                "vote_id": vote_event_id, # ID for the roll call event
                "congress": congress,
                "session": session,
                "chamber": chamber,
                "roll_call": roll_call,
                "vote_date": self._parse_congress_datetime(vote_details.get('date')), # Use datetime for votes
                "vote_question": vote_details.get('question'),
                "vote_type": vote_details.get('type'),
                "vote_result": vote_details.get('result'),
                "source_url": vote_details.get('url'), # URL to the vote details page
                # Bill Details (if linked)
                "bill_id": bill_id,
                "bill_title": bill_info.get('title') if bill_info else None, # Usually not in vote record itself
                "source": "Congress.gov API",
            }
            # Filter out None values before potential Pydantic validation
            filtered_processed = {k: v for k, v in processed.items() if v is not None}
            if not filtered_processed.get('bioguide_id') or not filtered_processed.get('position'):
                 logger.warning(f"Skipping processed vote due to missing bioguide_id or position: {vote_event_id}")
                 return None

            # Use Pydantic model for validation if available
            # return Vote(**filtered_processed).model_dump(exclude_none=True)
            return filtered_processed
        except Exception as e:
            # Log error with vote ID if available
            vote_event_id = f"{vote_data.get('vote',{}).get('congress')}-{vote_data.get('vote',{}).get('chamber')}-{vote_data.get('vote',{}).get('session')}-{vote_data.get('vote',{}).get('rollCallNumber')}"
            logger.error(f"Error processing Congress vote data: {vote_event_id} - {e}", exc_info=True)
            return None

    def process_votes(self, raw_vote_list: List[Dict[str, Any]], member_bioguide_id: Optional[str] = None) -> List[Dict]:
        """Processes a list of raw vote records."""
        logger.info(f"Processing {len(raw_vote_list)} raw Congress vote records for member {member_bioguide_id or 'Unknown'}...")
        processed_list = []
        for raw_data in raw_vote_list:
            processed = self.process_vote(raw_data, member_bioguide_id)
            if processed:
                processed_list.append(processed)
        logger.info(f"Successfully processed {len(processed_list)} Congress vote records.")
        return processed_list


    def process_bill(self, bill_data: Dict[str, Any]) -> Optional[Dict]:
        """Processes a single raw bill record from Congress API."""
        try:
            congress = bill_data.get('congress')
            bill_type = bill_data.get('type', '').lower()
            number = bill_data.get('number')
            if not all([congress, bill_type, number]):
                 logger.warning(f"Skipping bill record due to missing identifiers: {bill_data.get('url')}")
                 return None

            bill_id = f"{congress}-{bill_type}-{number}"
            sponsor_info = bill_data.get('sponsors', [{}])[0] if bill_data.get('sponsors') else {}

            processed = {
                "bill_id": bill_id,
                "congress": congress,
                "bill_type": bill_type,
                "bill_number": number,
                "title": bill_data.get('title'),
                "short_title": bill_data.get('titles', [{}])[0].get('title') if bill_data.get('titles') else None, # First title often short title
                "introduced_date": self._parse_congress_date(bill_data.get('introducedDate')),
                "sponsor_bioguide_id": sponsor_info.get('bioguideId'),
                # Extract cosponsor IDs if available (API structure varies)
                "cosponsors_count": bill_data.get('cosponsors', {}).get('count'),
                "latest_action_text": bill_data.get('latestAction', {}).get('text'),
                "latest_action_date": self._parse_congress_date(bill_data.get('latestAction', {}).get('actionDate')),
                "policy_area": bill_data.get('policyArea', {}).get('name'),
                "subjects": [subj.get('name') for subj in bill_data.get('subjects', {}).get('legislativeSubjects', []) if subj.get('name')], # Extract subject names
                "summary_text": bill_data.get('summaries', {}).get('latestSummary', {}).get('text'), # Get latest summary text
                "source": "Congress.gov API",
                "source_url": bill_data.get('url'),
            }
            # Use Pydantic model for validation if available
            # return Bill(**processed).model_dump(exclude_none=True)
            return {k: v for k, v in processed.items() if v is not None}
        except Exception as e:
             bill_id = f"{bill_data.get('congress')}-{bill_data.get('type', '').lower()}-{bill_data.get('number')}"
             logger.error(f"Error processing Congress bill data: {bill_id} - {e}", exc_info=True)
             return None

    def process_bills(self, raw_bill_list: List[Dict[str, Any]]) -> List[Dict]:
        """Processes a list of raw bill records."""
        logger.info(f"Processing {len(raw_bill_list)} raw Congress bill records...")
        processed_list = []
        for raw_data in raw_bill_list:
            processed = self.process_bill(raw_data)
            if processed:
                processed_list.append(processed)
        logger.info(f"Successfully processed {len(processed_list)} Congress bill records.")
        return processed_list

    # Add methods for processing Committee data if needed

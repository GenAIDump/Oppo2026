# File: Oppo/data_collection/processors/opensecrets_processor.py
# Purpose: Processes raw OpenSecrets API data into standardized Data Models.
# Note: In MCP architecture, this processor would format data and send
# structured requests (e.g., AddDonation, UpdateCandidateFinance) to the MCP Server API.

import logging
import os
from datetime import datetime, date, timezone
from typing import Dict, List, Any, Optional
import re
import json # For potential serialization if sending complex data to MCP

# Import specific data models
try:
    # Adjust path based on actual project structure if needed
    from database.data_models import Candidate, Donation # Add other models like IndustryContribution if processing those
    MODELS_LOADED = True
except ImportError:
     # Fallback if models aren't easily importable (e.g., running script standalone)
     logging.error("Could not import data models for OpenSecretsProcessor. Processing will use dicts.")
     MODELS_LOADED = False
     # Define dummy classes or skip type hinting
     class Candidate: pass
     class Donation: pass

# Import config if needed
try:
    from a2a_host.config import LOG_LEVEL
    CONFIG_LOADED = True
except ImportError:
     # Ensure logging configured if run standalone
     log_level_env = os.getenv("LOG_LEVEL", "INFO").upper()
     logging.basicConfig(level=getattr(logging, log_level_env, logging.INFO), format='%(asctime)s:%(levelname)s:%(name)s:%(lineno)d:%(message)s')
     LOG_LEVEL = log_level_env
     CONFIG_LOADED = False

# Ensure logging is configured before use (again, safe if already done)
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format='%(asctime)s:%(levelname)s:%(name)s:%(lineno)d:%(message)s',
    force=True # Reconfigure if needed
)
logger = logging.getLogger(__name__)


class OpenSecretsProcessor:
    """
    Processes raw data fetched from the OpenSecrets API into structured formats
    ready for storage (ideally via MCP Server).
    """

    def __init__(self):
        """Initializes the OpenSecrets processor."""
        logger.info("OpenSecretsProcessor initialized.")
        # In MCP architecture, this processor typically doesn't need a direct DB client.
        # It would format data and make HTTP requests to MCP server endpoints.

    def _parse_opensecrets_date(self, date_string: Optional[str]) -> Optional[date]:
        """Safely parses MM/DD/YYYY date strings commonly found in OpenSecrets data."""
        if not date_string:
            return None
        try:
            # OpenSecrets often uses MM/DD/YYYY
            return datetime.strptime(date_string, '%m/%d/%Y').date()
        except (ValueError, TypeError):
            logger.debug(f"Could not parse OpenSecrets date string: {date_string}")
            return None

    def _safe_float(self, value: Any) -> Optional[float]:
        """Safely converts a value to float, handling errors and non-numeric strings."""
        if value is None: return None
        try:
            # Remove common currency symbols or commas if present
            if isinstance(value, str):
                value = value.replace('$', '').replace(',', '').strip()
                if not value: return None # Handle empty string after cleaning
            return float(value)
        except (ValueError, TypeError):
            logger.debug(f"Could not convert value to float: {value}")
            return None

    def _standardize_party(self, party_code: Optional[str]) -> Optional[str]:
        """Standardizes party codes."""
        if not party_code or not isinstance(party_code, str): return None
        p = party_code.upper()
        if p == 'R': return 'GOP'
        if p == 'D': return 'DEM'
        if p == 'I': return 'IND'
        # Add L for Libertarian, G for Green?
        return p # Return original if no match

    def _extract_state_district_from_office(self, office: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
         """ Tries to extract state (XX) and district (XX-YY or XX-L) from office string """
         if not office or not isinstance(office, str): return None, None
         office = office.upper()
         state, district_std = None, None
         # Try parsing state/district from office code like TX06, CA33
         match_house = re.match(r"([A-Z]{2})(\d{2})", office)
         # Try parsing state from office code like CAS1 (Senate Class 1)
         match_senate = re.match(r"([A-Z]{2})S\d?", office)
         if match_house:
              state = match_house.group(1)
              district_num = match_house.group(2)
              district_std = f"{state}-{district_num}"
         elif match_senate:
              state = match_senate.group(1)
              district_std = f"{state}-SEN" # Indicate Senate
         elif len(office) == 2 and office.isalpha(): # Handle case where office is just State for Senate maybe?
              state = office
              district_std = f"{state}-SEN" # Assumption
         return state, district_std


    def process_candidate_summary(self, summary_attributes: Dict[str, Any]) -> Optional[Dict]:
        """
        Processes the '@attributes' dict from candSummary or memPFDSummary.
        Outputs a dictionary suitable for updating a Candidate node via MCP.
        """
        if not summary_attributes or not isinstance(summary_attributes, dict):
            logger.warning("Invalid candidate summary attributes received.")
            return None
        try:
            cid = summary_attributes.get('cid')
            if not cid:
                logger.warning("Skipping OpenSecrets summary: Missing CID.")
                return None

            # Generate a stable candidate ID based on OpenSecrets CID
            stable_id = f"os_{cid}"

            # Extract and clean fields
            name = summary_attributes.get('firstlast')
            party = self._standardize_party(summary_attributes.get('party'))
            office = summary_attributes.get('office') # e.g., 'TX06', 'PRES', 'Delaware Senate seat'
            state, district_std = self._extract_state_district_from_office(office)
            # Fallback for state if not in office string
            if not state: state = summary_attributes.get('state')

            office_sought = None
            if office == 'PRES': office_sought = "President"
            elif district_std and 'SEN' in district_std: office_sought = "US Senate"
            elif district_std: office_sought = "US House"
            else: office_sought = office # Store original if unknown format

            processed = {
                "candidate_id": stable_id, # ID strategy needs careful consideration
                "opensecrets_id": cid,
                "name": name,
                "party": party,
                "state": state[:2].upper() if state else None, # Ensure 2 char state code
                "district": district_std,
                "office_sought": office_sought, # Standardized or original
                # Financials
                "opensecrets_total_receipts": self._safe_float(summary_attributes.get('total')),
                "opensecrets_total_spent": self._safe_float(summary_attributes.get('spent')),
                "opensecrets_cash_on_hand": self._safe_float(summary_attributes.get('cash_on_hand')),
                "opensecrets_debt": self._safe_float(summary_attributes.get('debt')),
                "opensecrets_last_updated": self._parse_opensecrets_date(summary_attributes.get('last_updated')),
                "source": "OpenSecrets", # Add source context
                "source_url": f"https://www.opensecrets.org/members-of-congress/summary?cid={cid}",
                # Add other fields like 'origin', 'first_elected' if available
            }

            # Use Pydantic model for validation if available
            # if MODELS_LOADED: validated_data = Candidate(**processed).model_dump(exclude_none=True)
            # Return dict without None values
            return {k: v for k, v in processed.items() if v is not None}

        except Exception as e:
            logger.error(f"Error processing OpenSecrets candidate summary data (CID: {summary_attributes.get('cid')}): {e}", exc_info=True)
            return None


    def process_contributor_aggregate(self, contributor_attributes: Dict[str, Any], candidate_os_id: str, cycle: int) -> Optional[Dict]:
        """
        Processes a single contributor record's '@attributes' from candContrib.
        Represents aggregate contributions related to an organization.
        Outputs data suitable for creating/updating Org nodes and relationships via MCP.
        """
        if not contributor_attributes or not isinstance(contributor_attributes, dict):
            return None
        try:
            org_name = contributor_attributes.get('org_name')
            total_amount = self._safe_float(contributor_attributes.get('total'))
            if not org_name or total_amount is None:
                 logger.debug("Skipping contributor aggregate due to missing org_name or total amount.")
                 return None

            # This represents an aggregate. Structure for MCP call.
            opensecrets_org_id = contributor_attributes.get('orgid')

            processed = {
                "candidate_opensecrets_id": candidate_os_id, # Link back to candidate OS ID
                "election_cycle": cycle,
                "contributor_org_name": org_name,
                "contributor_opensecrets_orgid": opensecrets_org_id,
                "aggregate_total_amount": total_amount,
                "aggregate_individual_amount": self._safe_float(contributor_attributes.get('indivs')),
                "aggregate_pac_amount": self._safe_float(contributor_attributes.get('pacs')),
                "source": "OpenSecrets candContrib",
                # Link to org page if ID exists
                "source_url": f"https://www.opensecrets.org/orgs/summary?id={opensecrets_org_id}" if opensecrets_org_id else None,
            }
            # NOTE: This dict needs sending to an MCP endpoint to handle Org node + Relationship merge.
            return {k: v for k, v in processed.items() if v is not None}
        except Exception as e:
             logger.error(f"Error processing OpenSecrets contributor aggregate (Org: {contributor_attributes.get('org_name')}): {e}", exc_info=True)
             return None

    def process_contributors(self, raw_contributor_list: List[Dict[str, Any]], candidate_os_id: str, cycle: int) -> List[Dict]:
        """Processes a list of raw contributor aggregate records for a candidate."""
        logger.info(f"Processing {len(raw_contributor_list)} OpenSecrets contributor aggregate records for OS_ID {candidate_os_id}...")
        processed_list = []
        for raw_data in raw_contributor_list:
             attributes = raw_data.get('@attributes', {})
             processed = self.process_contributor_aggregate(attributes, candidate_os_id, cycle)
             if processed:
                  processed_list.append(processed)
        logger.info(f"Successfully processed {len(processed_list)} OpenSecrets contributor aggregate records.")
        # NOTE: The caller should send this list to MCP Server.
        return processed_list


    def process_industry_aggregate(self, industry_attributes: Dict[str, Any], candidate_os_id: str, cycle: int) -> Optional[Dict]:
        """
        Processes a single industry record's '@attributes' from candIndustry.
        Represents aggregate contributions related to an industry.
        """
        if not industry_attributes or not isinstance(industry_attributes, dict):
            return None
        try:
            industry_name = industry_attributes.get('industry_name')
            industry_code = industry_attributes.get('industry_code') # Cat Code
            total_amount = self._safe_float(industry_attributes.get('total'))
            if not industry_name or not industry_code or total_amount is None:
                 logger.debug("Skipping industry aggregate due to missing name, code, or total amount.")
                 return None

            processed = {
                "candidate_opensecrets_id": candidate_os_id,
                "election_cycle": cycle,
                "industry_name": industry_name,
                "industry_code": industry_code,
                "aggregate_total_amount": total_amount,
                "aggregate_individual_amount": self._safe_float(industry_attributes.get('indivs')),
                "aggregate_pac_amount": self._safe_float(industry_attributes.get('pacs')),
                "rank": int(industry_attributes['rank']) if industry_attributes.get('rank') and industry_attributes['rank'].isdigit() else None,
                "source": "OpenSecrets candIndustry",
            }
            # NOTE: This dict needs sending to an MCP endpoint to handle Industry node + Relationship merge.
            return {k: v for k, v in processed.items() if v is not None}
        except Exception as e:
             logger.error(f"Error processing OpenSecrets industry aggregate (Industry: {industry_attributes.get('industry_name')}): {e}", exc_info=True)
             return None

    def process_industries(self, raw_industry_list: List[Dict[str, Any]], candidate_os_id: str, cycle: int) -> List[Dict]:
        """Processes a list of raw industry aggregate records for a candidate."""
        logger.info(f"Processing {len(raw_industry_list)} OpenSecrets industry aggregate records for OS_ID {candidate_os_id}...")
        processed_list = []
        for raw_data in raw_industry_list:
             attributes = raw_data.get('@attributes', {})
             processed = self.process_industry_aggregate(attributes, candidate_os_id, cycle)
             if processed:
                  processed_list.append(processed)
        logger.info(f"Successfully processed {len(processed_list)} OpenSecrets industry aggregate records.")
        # NOTE: The caller should send this list to MCP Server.
        return processed_list

    # Add methods for processing other OpenSecrets data types (candSector, orgSummary, lobbying) if needed

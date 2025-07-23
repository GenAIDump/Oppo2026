# File: Oppo/data_collection/processors/fec_processor.py
# Purpose: Processes raw FEC API data into standardized Data Models.
# Note: In MCP architecture, this processor would typically format data
# and send structured requests (e.g., AddCandidate, AddContribution) to the MCP Server API.

import logging
import os
from datetime import datetime, date, timezone
from typing import Dict, List, Any, Optional
import uuid # For generating candidate_id if missing
import re

# Import specific data models for type hinting and structure validation
try:
    # Adjust path based on actual project structure if needed
    from database.data_models import Candidate, Contribution, Expenditure # Add Committee if processing that data
    MODELS_LOADED = True
except ImportError:
     # Fallback if models aren't easily importable (e.g., running script standalone)
     logging.error("Could not import data models for FECProcessor. Processing will use dicts.")
     MODELS_LOADED = False
     # Define dummy classes or skip type hinting
     class Candidate: pass
     class Contribution: pass
     class Expenditure: pass

# Import config if needed (e.g., for logging level)
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


class FECProcessor:
    """
    Processes raw data fetched from the FEC API into structured Pydantic models
    (or dictionaries) ready for storage (ideally via MCP Server).
    """

    def __init__(self):
        """Initializes the FEC processor."""
        logger.info("FECProcessor initialized.")
        # In MCP architecture, this processor typically doesn't need a direct DB client.
        # It would format data and make HTTP requests to MCP server endpoints.

    def _parse_date(self, date_string: Optional[str]) -> Optional[date]:
        """Safely parses YYYY-MM-DD date strings."""
        if not date_string:
            return None
        try:
            # FEC API typically uses YYYY-MM-DD
            return datetime.strptime(date_string, '%Y-%m-%d').date()
        except (ValueError, TypeError):
            logger.debug(f"Could not parse FEC date string: {date_string}")
            return None

    def _standardize_party(self, party_code: Optional[str]) -> Optional[str]:
        """Standardizes party codes."""
        if not party_code or not isinstance(party_code, str): return None
        p = party_code.strip().upper()
        if p in ['REP', 'R']: return 'GOP'
        if p in ['DEM', 'D']: return 'DEM'
        if p in ['IND', 'I', 'NNE', 'NPA', 'OTH']: return 'IND' # Group various non-major parties
        if p == 'LIB': return 'LIB'
        if p == 'GRE': return 'GRN'
        # Add others as needed
        return p # Return original cleaned code if no match

    def _format_district(self, state: Optional[str], district_num: Optional[Any]) -> Optional[str]:
         """Formats state and district number into standard XX-YY or XX-L format."""
         if not state or district_num is None: return None
         state = str(state).strip().upper()
         district_str = str(district_num).strip().upper()
         if not state or len(state) != 2 or not state.isalpha():
              logger.debug(f"Invalid state code '{state}' for district formatting.")
              return None

         if district_str in ['L', '0', '00', 'AT LARGE', 'AL']:
              return f"{state}-L"
         elif district_str.isdigit():
              return f"{state}-{int(district_str):02d}" # Pad with zero if needed
         else:
             # Handle cases like district '1 ' or maybe already formatted
             if district_str.replace(" ","").isdigit():
                  return f"{state}-{int(district_str):02d}"
             elif f"{state}-" in district_str: # Check if already formatted
                  return district_str
             logger.warning(f"Could not format district number '{district_num}' for state '{state}'.")
             return None

    def _generate_candidate_id(self, fec_id: Optional[str], name: Optional[str], district: Optional[str]) -> Optional[str]:
        """
        Generates a stable candidate ID. Prefers FEC ID, falls back to name/district hash.
        Args:
            fec_id: FEC Candidate ID (e.g., H0CA01234)
            name: Candidate Name
            district: Standardized district (e.g., CA-10)
        """
        if fec_id and isinstance(fec_id, str) and fec_id.strip():
             # Prefix FEC ID to indicate source and ensure uniqueness across sources
             return f"fec_{fec_id.strip()}"
        # Fallback: Create ID based on name/district (less reliable for matching across sources)
        if name and district:
            name_part = re.sub(r'\W+', '', name).lower()
            dist_part = re.sub(r'\W+', '', district).lower()
            fallback_id = f"cand_{name_part}_{dist_part}"[:64] # Limit length
            logger.warning(f"Generated fallback candidate_id '{fallback_id}' for candidate '{name}' (FEC ID missing). Use with caution for merging.")
            return fallback_id
        logger.error(f"Could not generate candidate_id: Missing FEC ID and Name/District. Name='{name}', District='{district}'")
        return None


    def process_candidate(self, candidate_data: Dict[str, Any]) -> Optional[Dict]:
        """Processes a single raw candidate record from FEC search or detail endpoint."""
        if not candidate_data or not isinstance(candidate_data, dict):
             logger.warning("Received invalid candidate data for processing.")
             return None
        try:
            fec_id = candidate_data.get('candidate_id')
            name = candidate_data.get('name')
            party_raw = candidate_data.get('party')
            state_raw = candidate_data.get('state')
            # District can be 'district' (XX) or 'district_number' (int)
            district_num = candidate_data.get('district_number')
            if district_num is None: # Try 'district' field if 'district_number' is missing
                district_num = candidate_data.get('district')
            office_raw = candidate_data.get('office_sought', candidate_data.get('office')) # H, S, P

            # --- Data Cleaning & Standardization ---
            party_std = self._standardize_party(party_raw)
            state_std = str(state_raw).strip().upper() if state_raw else None
            district_std = self._format_district(state_std, district_num)

            # Determine office sought
            office_sought_std = None
            if office_raw == 'H': office_sought_std = 'US House'
            elif office_raw == 'S': office_sought_std = 'US Senate'
            elif office_raw == 'P': office_sought_std = 'President'

            # Generate a stable ID
            stable_id = self._generate_candidate_id(fec_id, name, district_std)
            if not stable_id:
                 logger.warning(f"Could not generate stable ID for candidate '{name}'. Skipping record.")
                 return None

            processed = {
                "candidate_id": stable_id,
                "fec_id": fec_id,
                "name": name,
                "party": party_std, # Standardized party
                "party_full": candidate_data.get('party_full'), # Full party name
                "office_sought": office_sought_std,
                "state": state_std,
                "district": district_std, # Standardized district
                "election_years": sorted(list(set(candidate_data.get('election_years', [])))), # Unique sorted years
                "first_file_date": self._parse_date(candidate_data.get('first_file_date')),
                "last_file_date": self._parse_date(candidate_data.get('last_fec_file_date', candidate_data.get('last_file_date'))),
                "source": "FEC",
                "source_url": f"https://www.fec.gov/data/candidate/{fec_id}/" if fec_id else None,
                "candidate_status": candidate_data.get('candidate_status'), # P, C, F, N, I
                "incumbent_challenger_status": candidate_data.get('incumbent_challenge_full') # Incumbent, Challenger, Open seat
            }
            # Use Pydantic model for validation if available and return dict
            if MODELS_LOADED:
                try:
                    validated_data = Candidate(**processed).model_dump(exclude_none=True)
                    return validated_data
                except Exception as pydantic_error: # Catch validation errors
                    logger.error(f"Pydantic validation failed for FEC candidate {stable_id}: {pydantic_error}")
                    return None # Skip invalid records
            else:
                return {k: v for k, v in processed.items() if v is not None}

        except Exception as e:
            logger.error(f"Error processing FEC candidate data: {candidate_data.get('candidate_id')} - {e}", exc_info=True)
            return None

    def process_candidates(self, raw_candidate_list: List[Dict[str, Any]]) -> List[Dict]:
        """Processes a list of raw candidate records."""
        logger.info(f"Processing {len(raw_candidate_list)} raw FEC candidate records...")
        processed_list = []
        for raw_data in raw_candidate_list:
            processed = self.process_candidate(raw_data)
            if processed:
                processed_list.append(processed)
        logger.info(f"Successfully processed {len(processed_list)} FEC candidate records.")
        # In MCP arch, this list would be sent to MCP endpoint(s) for storage.
        return processed_list


    def process_contribution(self, contrib_data: Dict[str, Any]) -> Optional[Dict]:
        """Processes a single raw contribution record (Schedule A)."""
        if not contrib_data or not isinstance(contrib_data, dict):
             logger.warning("Received invalid contribution data for processing.")
             return None
        try:
            sub_id = contrib_data.get('sub_id') # Seems to be the unique transaction ID
            if not sub_id:
                 logger.warning(f"Skipping contribution record: Missing 'sub_id'. Data: {str(contrib_data)[:200]}")
                 return None

            amount = None
            try:
                 # contribution_receipt_amount seems correct for Sch A
                 amount = float(contrib_data.get('contribution_receipt_amount', 0.0))
            except (ValueError, TypeError):
                 logger.warning(f"Invalid contribution amount: {contrib_data.get('contribution_receipt_amount')}, Sub ID: {sub_id}")
                 return None # Skip records with invalid amounts

            fec_candidate_id = contrib_data.get('candidate_id') # Can be null if to non-candidate cmte
            recipient_committee_id = contrib_data.get('committee_id')
            if not recipient_committee_id:
                 logger.warning(f"Skipping contribution record: Missing recipient 'committee_id'. Sub ID: {sub_id}")
                 return None

            # Generate stable ID for the recipient candidate if FEC ID is available
            recipient_candidate_stable_id = self._generate_candidate_id(fec_candidate_id, None, None) if fec_candidate_id else None

            # Determine contributor type more granularly if possible
            entity_type = contrib_data.get('entity_type') # e.g., IND, ORG, COM, PAC
            entity_type_desc = contrib_data.get('entity_type_desc') # e.g., INDIVIDUAL, ORGANIZATION
            contributor_type = entity_type_desc or entity_type # Prefer description

            processed = {
                "transaction_id": f"fec_contrib_{sub_id}", # Make tx id source-specific
                "fec_sub_id": sub_id,
                # Linkages
                "recipient_candidate_id": recipient_candidate_stable_id, # Link to our candidate ID
                "recipient_fec_candidate_id": fec_candidate_id,
                "recipient_committee_id": recipient_committee_id, # Link to Committee node
                # Contributor Info
                "contributor_name": contrib_data.get('contributor_name'),
                "contributor_first_name": contrib_data.get('contributor_first_name'),
                "contributor_last_name": contrib_data.get('contributor_last_name'),
                "contributor_type": contributor_type,
                "contributor_occupation": contrib_data.get('contributor_occupation'),
                "contributor_employer": contrib_data.get('contributor_employer'),
                "contributor_city": contrib_data.get('contributor_city'),
                "contributor_state": contrib_data.get('contributor_state'),
                "contributor_zip": contrib_data.get('contributor_zip_code'),
                # Transaction Details
                "amount": amount,
                "date": self._parse_date(contrib_data.get('contribution_receipt_date')),
                "memo_text": contrib_data.get('memo_text'),
                "fec_election_type_desc": contrib_data.get('fec_election_type_desc'), # e.g., PRIMARY, GENERAL
                "two_year_transaction_period": contrib_data.get('two_year_transaction_period'), # e.g., 2024
                # Source Info
                "source": "FEC Schedule A",
                "source_url": f"https://www.fec.gov/data/receipts/?sub_id={sub_id}",
            }
            # Use Pydantic model for validation if available
            if MODELS_LOADED:
                 try:
                      validated_data = Donation(**processed).model_dump(exclude_none=True)
                      return validated_data
                 except Exception as pydantic_error:
                      logger.error(f"Pydantic validation failed for FEC contribution {sub_id}: {pydantic_error}")
                      return None
            else:
                 return {k: v for k, v in processed.items() if v is not None}

        except Exception as e:
            logger.error(f"Error processing FEC contribution data: {contrib_data.get('sub_id')} - {e}", exc_info=True)
            return None

    def process_contributions(self, raw_contribution_list: List[Dict[str, Any]]) -> List[Dict]:
        """Processes a list of raw contribution records."""
        logger.info(f"Processing {len(raw_contribution_list)} raw FEC contribution records...")
        processed_list = []
        for raw_data in raw_contribution_list:
            processed = self.process_contribution(raw_data)
            if processed:
                processed_list.append(processed)
        logger.info(f"Successfully processed {len(processed_list)} FEC contribution records.")
        # In MCP arch, this list would be sent to MCP endpoint(s) for storage.
        return processed_list


    def process_expenditure(self, expend_data: Dict[str, Any]) -> Optional[Dict]:
        """Processes a single raw expenditure record (Schedule B)."""
        if not expend_data or not isinstance(expend_data, dict):
             logger.warning("Received invalid expenditure data for processing.")
             return None
        try:
            sub_id = expend_data.get('sub_id')
            if not sub_id:
                 logger.warning(f"Skipping expenditure record: Missing 'sub_id'. Data: {str(expend_data)[:200]}")
                 return None

            amount = None
            try:
                 # disbursement_amount seems correct for Sch B
                 amount = float(expend_data.get('disbursement_amount', 0.0))
            except (ValueError, TypeError):
                 logger.warning(f"Invalid expenditure amount: {expend_data.get('disbursement_amount')}, Sub ID: {sub_id}")
                 return None

            spender_committee_id = expend_data.get('committee_id')
            if not spender_committee_id:
                 logger.warning(f"Skipping expenditure record: Missing spender 'committee_id'. Sub ID: {sub_id}")
                 return None

            fec_candidate_id = expend_data.get('candidate_id') # Candidate related to spender committee (often null)
            spender_candidate_stable_id = self._generate_candidate_id(fec_candidate_id, None, None) if fec_candidate_id else None

            processed = {
                "transaction_id": f"fec_expend_{sub_id}",
                "fec_sub_id": sub_id,
                # Linkages
                "spender_committee_id": spender_committee_id,
                "spender_candidate_id": spender_candidate_stable_id, # Link to candidate if available
                # Payee Info
                "payee_name": expend_data.get('recipient_name'),
                "payee_city": expend_data.get('recipient_city'),
                "payee_state": expend_data.get('recipient_state'),
                 "payee_zip": expend_data.get('recipient_zip_code'),
                # Transaction Details
                "amount": amount,
                "date": self._parse_date(expend_data.get('disbursement_date')),
                "purpose": expend_data.get('disbursement_purpose', expend_data.get('disbursement_description')),
                "category": expend_data.get('disbursement_type_description'), # e.g., ADVERTISING, SALARIES
                "two_year_transaction_period": expend_data.get('two_year_transaction_period'),
                # Source Info
                "source": "FEC Schedule B",
                "source_url": f"https://www.fec.gov/data/disbursements/?sub_id={sub_id}",
            }
            # Use Pydantic model for validation if available
            if MODELS_LOADED:
                 try:
                      validated_data = Expenditure(**processed).model_dump(exclude_none=True)
                      return validated_data
                 except Exception as pydantic_error:
                      logger.error(f"Pydantic validation failed for FEC expenditure {sub_id}: {pydantic_error}")
                      return None
            else:
                return {k: v for k, v in processed.items() if v is not None}
        except Exception as e:
            logger.error(f"Error processing FEC expenditure data: {expend_data.get('sub_id')} - {e}", exc_info=True)
            return None

    def process_expenditures(self, raw_expenditure_list: List[Dict[str, Any]]) -> List[Dict]:
        """Processes a list of raw expenditure records."""
        logger.info(f"Processing {len(raw_expenditure_list)} raw FEC expenditure records...")
        processed_list = []
        for raw_data in raw_expenditure_list:
            processed = self.process_expenditure(raw_data)
            if processed:
                processed_list.append(processed)
        logger.info(f"Successfully processed {len(processed_list)} FEC expenditure records.")
        # In MCP arch, send to MCP endpoint(s).
        return processed_list

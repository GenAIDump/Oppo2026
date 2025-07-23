# File: Oppo/scripts/ingest_candidates_csv.py
# Purpose: Script to read candidate data from a CSV and ingest/update via MCP Server API.

import logging
import os
import sys
import argparse
import time
import re
import requests # To call MCP Server API
from typing import Dict, List, Optional, Any
from urllib.parse import urlparse

# Requires pandas library: pip install pandas
try:
    import pandas as pd
except ImportError:
     print("ERROR: pandas library not found. Please install it: pip install pandas")
     sys.exit(1)


# --- Configuration Loading ---
# Add project root to Python path to allow importing config from a2a_host
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

try:
    # Assuming config is importable when script is run relative to project root
    from a2a_host.config import MCP_SERVER_URL, INTERNAL_SERVICE_API_KEY, LOG_LEVEL
    CONFIG_LOADED = True
except ImportError as e:
     # Fallback if running script standalone and config is not easily importable
     # Ensure logging is configured if this fails
     log_level_env = os.getenv("LOG_LEVEL", "INFO").upper()
     logging.basicConfig(
         level=getattr(logging, log_level_env, logging.INFO),
         format='%(asctime)s - %(levelname)s - %(name)s - %(message)s'
         )
     logger = logging.getLogger(__name__) # Need logger instance here
     logger.warning(f"Could not import config from a2a_host ({e}). Loading MCP_SERVER_URL/INTERNAL_SERVICE_API_KEY from environment.")
     MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://localhost:8001") # Default for local Docker
     INTERNAL_SERVICE_API_KEY = os.getenv("INTERNAL_SERVICE_API_KEY")
     LOG_LEVEL = log_level_env
     CONFIG_LOADED = False # Mark that loading from config module failed

# --- Logging Setup ---
# Ensure logging is configured properly regardless of how config was loaded
log_level_to_set = getattr(logging, LOG_LEVEL, logging.INFO)
logging.basicConfig(
    level=log_level_to_set,
    format='%(asctime)s - %(levelname)s - %(name)s:%(lineno)d - %(message)s',
    force=True # Force reconfiguration if basicConfig was called earlier
)
logger = logging.getLogger(__name__)
logging.getLogger("requests").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logger.info(f"Ingestion script logging level set to: {LOG_LEVEL}")


# --- Helper Functions ---

def extract_state_from_district(district: Optional[str]) -> Optional[str]:
    """Extracts 2-letter state code from district string (e.g., PA-01 -> PA, SD-L -> SD)."""
    if district and isinstance(district, str):
        # Match patterns like XX-YY, XX_YY, XX YY, XX-L, XXL
        match = re.match(r"([A-Z]{2})[-_ ]?(\d+|L)", district.strip().upper())
        if match:
            return match.group(1)
        # Handle state-only cases like 'MT' if district is just state code sometimes
        if len(district.strip()) == 2 and district.strip().isalpha():
            return district.strip().upper()
    return None

def format_district(state: Optional[str], district_num_or_l: Optional[Any]) -> Optional[str]:
     """Formats state and district number into standard XX-YY or XX-L format."""
     if not state or district_num_or_l is None:
         return None
     state = state.upper()
     district_str = str(district_num_or_l).strip().upper().replace('AT-LARGE','L').replace('AT LARGE','L')
     if district_str in ['L', '0', '00']:
          return f"{state}-L"
     elif district_str.isdigit():
          return f"{state}-{int(district_str):02d}" # Pad with zero if needed
     else: # Handle cases where district might already be formatted?
         if f"{state}-" in district_str: return district_str
         logger.warning(f"Could not format district number '{district_num_or_l}' for state '{state}'.")
         return None


def generate_candidate_id(name: Optional[str], district: Optional[str]) -> Optional[str]:
     """Generates a simple, repeatable candidate ID based on name and standardized district."""
     if not name or not district: # Requires standardized district
         return None
     # Remove non-alphanumeric, convert to lower
     name_part = re.sub(r'\W+', '', name).lower()
     dist_part = re.sub(r'\W+', '', district).lower() # e.g., pa01 or sdl
     # Simple concatenation - collisions possible but less likely with district
     return f"cand_{name_part}_{dist_part}"[:64] # Limit length, allow more than 50


def parse_youtube_id(url: Optional[str]) -> Optional[str]:
     """Extracts YouTube Channel ID or @handle from various URL formats."""
     if not url or not isinstance(url, str): return None
     url = url.strip()
     parsed = urlparse(url)

     # Standard YouTube URLs
     if 'youtube.com' in parsed.netloc:
          path_parts = [p for p in parsed.path.split('/') if p]
          if len(path_parts) > 0:
               if path_parts[0] == 'channel' and len(path_parts) > 1:
                    # Check if it looks like a channel ID (starts with UC, 24 chars)
                    if path_parts[1].startswith('UC') and len(path_parts[1]) == 24 and path_parts[1].isalnum():
                        return path_parts[1]
               elif path_parts[0].startswith('@'):
                    # Extract handle (starts with @, valid characters)
                    handle_match = re.match(r'^@([a-zA-Z0-9_.-]+)$', path_parts[0])
                    if handle_match:
                         return path_parts[0] # Return the full handle @username
               elif path_parts[0] == 'c' and len(path_parts) > 1:
                    # Legacy custom URL - return handle part
                    logger.debug(f"Found legacy custom URL handle '/c/{path_parts[1]}'. Storing handle.")
                    return path_parts[1]
               elif path_parts[0] == 'user' and len(path_parts) > 1:
                    # Legacy username URL - return username part
                    logger.debug(f"Found legacy username URL '/user/{path_parts[1]}'. Storing username.")
                    return path_parts[1]


     # Check googleusercontent format from CSV example
     if 'googleusercontent.com' in parsed.netloc and 'youtube.com' in parsed.netloc:
          path_part = parsed.path.strip('/')
          if path_part.startswith('UC') and len(path_part) == 24 and path_part.isalnum():
               return path_part
          elif path_part.startswith('@'):
               return path_part
          else:
               logger.debug(f"Could not parse known ID/handle pattern from googleusercontent URL path: {path_part}")

     logger.debug(f"Could not extract YouTube Channel ID or @handle from URL: {url}")
     return None # Return None if no known pattern matches


def call_mcp_api(
    session: requests.Session,
    method: str,
    endpoint: str,
    json_payload: Optional[Dict] = None,
    params: Optional[Dict] = None
) -> Optional[Dict]:
    """Helper function to call the MCP Server API."""
    if not MCP_SERVER_URL:
        logger.error("MCP_SERVER_URL not configured. Cannot call API.")
        return None

    url = f"{MCP_SERVER_URL.rstrip('/')}/{endpoint.lstrip('/')}"
    log_payload = f"{str(json_payload)[:200]}..." if json_payload else "None"
    logger.debug(f"MCP Call: {method.upper()} {url} Params: {params} Payload: {log_payload}")
    try:
        # Use headers defined in the session (includes internal API key if set)
        response = session.request(method, url, json=json_payload, params=params, timeout=30)
        response.raise_for_status() # Check for 4xx/5xx errors first
        data = response.json()
        # Check for application-level success status within the JSON response
        if isinstance(data, dict) and data.get("status") == "success":
             return data
        else:
             error_msg = data.get('message', data.get('detail', 'Unknown MCP error structure')) if isinstance(data, dict) else f"Non-dict response: {str(data)[:200]}"
             logger.error(f"MCP API returned non-success status for {method} {endpoint}: {error_msg}")
             return {"error": error_msg} # Return dict indicating error
    except requests.exceptions.HTTPError as e:
        # Log detailed error from response if possible
        error_detail = f"HTTP Error {e.response.status_code}"
        try:
             err_json = e.response.json()
             error_detail = err_json.get('detail', error_detail)
        except ValueError: # Not JSON
             error_detail = f"{error_detail} - Response: {e.response.text[:200]}"
        logger.error(f"HTTP Error calling MCP {method} {endpoint}: {error_detail}", exc_info=False)
        return {"error": error_detail}
    except requests.exceptions.RequestException as e:
        logger.error(f"Network Error calling MCP {method} {endpoint}: {e}", exc_info=False)
        return {"error": "Network Error"}
    except Exception as e:
        logger.error(f"Unexpected error calling MCP {method} {endpoint}: {e}", exc_info=True)
        return {"error": "Unexpected Processing Error"}


# --- Main Ingestion Logic ---

def ingest_candidates_from_csv(csv_filepath: str, trigger_relationships: bool = True):
    """Reads candidates from CSV and ingests/updates them via MCP Server API."""
    logger.info(f"Starting candidate ingestion from CSV: {csv_filepath}")

    if not MCP_SERVER_URL:
         logger.critical("MCP_SERVER_URL is not configured. Aborting ingestion.")
         return False
    # API Key check happens implicitly in call_mcp_api via session headers

    try:
        # Ensure file exists before reading
        if not os.path.exists(csv_filepath):
             logger.critical(f"CSV file not found at: {csv_filepath}")
             return False
        # Read CSV, handle potential Byte Order Mark (BOM) and various NA values
        df = pd.read_csv(
             csv_filepath,
             encoding='utf-8-sig',
             keep_default_na=False, # Keep empty strings as is initially
             na_values=['', '#N/A', '#N/A N/A', '#NA', '-1.#IND', '-1.#QNAN', '-NaN', '-nan', '1.#IND', '1.#QNAN', '<NA>', 'N/A', 'NA', 'NULL', 'NaN', 'n/a', 'nan', 'null']
        )
        df.columns = df.columns.str.strip() # Clean column names
        logger.info(f"Read {len(df)} rows from CSV.")
        # Convert empty strings explicitly to None *after* loading
        df = df.apply(lambda x: x.str.strip() if x.dtype == "object" else x).replace('', None)

    except Exception as e:
        logger.critical(f"Error reading or processing CSV file {csv_filepath}: {e}", exc_info=True)
        return False

    # Prepare session for MCP calls
    session = requests.Session()
    session.headers.update({"Accept": "application/json", "Content-Type": "application/json"})
    if INTERNAL_SERVICE_API_KEY:
        session.headers.update({"X-API-KEY": INTERNAL_SERVICE_API_KEY})
    else:
         logger.warning("INTERNAL_SERVICE_API_KEY not configured. MCP API calls might fail authentication.")


    ingested_count = 0
    updated_count = 0 # Can't easily distinguish create/update from MCP response yet
    failed_count = 0
    skipped_count = 0

    # --- Column Mapping (Confirm these match gop_youtube.csv exactly) ---
    name_col = 'member'
    party_col = 'party'
    district_col = 'district' # Expects format like 'XX-YY' or 'XX-L'
    youtube_col = 'yt_url' # YouTube URL column

    required_cols = [name_col, party_col, district_col]
    if not all(col in df.columns for col in required_cols):
        logger.critical(f"CSV missing required columns. Expected: {required_cols}. Found: {list(df.columns)}")
        session.close()
        return False

    logger.info(f"Starting ingestion loop for {len(df)} candidates...")
    for index, row in df.iterrows():
        row_num = index + 2 # For user-friendly logging (1-based index + header)
        try:
            name = row.get(name_col)
            party = row.get(party_col)
            district_raw = row.get(district_col) # Raw district from CSV

            # --- Basic Validation ---
            if pd.isna(name) or pd.isna(party) or pd.isna(district_raw):
                logger.warning(f"Skipping row {row_num}: Missing required data (name='{name}', party='{party}', district='{district_raw}').")
                skipped_count += 1
                continue

            # --- Data Cleaning & Standardization ---
            name = str(name).strip()
            party = str(party).strip().upper()
             # Standardize party
            if party in ["REPUBLICAN", "R"]: party = "GOP"
            elif party in ["DEMOCRAT", "D"]: party = "DEM"
            elif party in ["INDEPENDENT", "I"]: party = "IND"

            district_raw = str(district_raw).strip()
            state = extract_state_from_district(district_raw)
            if not state:
                 logger.warning(f"Skipping row {row_num} ('{name}'): Could not extract state from district '{district_raw}'.")
                 skipped_count += 1
                 continue
            # Format district after extracting state
            # Pass only the district part (number or L) to format_district
            dist_part_raw = district_raw.replace(f"{state}-",'').replace(f"{state}_",'').replace(f"{state} ",'') if district_raw else None
            district_std = format_district(state, dist_part_raw)
            if not district_std:
                 logger.warning(f"Skipping row {row_num} ('{name}'): Could not format district '{district_raw}'.")
                 skipped_count += 1
                 continue


            # Generate consistent Candidate ID
            candidate_id = generate_candidate_id(name, district_std)
            if not candidate_id:
                logger.warning(f"Skipping row {row_num} ('{name}'): Could not generate candidate ID from name '{name}' and district '{district_std}'.")
                skipped_count += 1
                continue

            # Parse YouTube URL
            youtube_url_raw = row.get(youtube_col)
            youtube_channel_identifier = parse_youtube_id(youtube_url_raw) # Returns ID or @handle

            # --- Prepare Payload for MCP ---
            # Use the CandidateRequest model fields implicitly
            payload = {
                "candidate_id": candidate_id,
                "name": name,
                "party": party,
                "state": state,
                "district": district_std,
                "office_sought": "US House", # Assumption based on CSV context
                "youtube_channel_id": youtube_channel_identifier,
                # Add other fields from CSV if mapped in data_models.CandidateRequest
                # e.g., "fec_id": row.get('fec_id'), if that column exists
            }
            # Remove keys with None values before sending
            payload = {k: v for k, v in payload.items() if v is not None}

            logger.debug(f"Ingesting Candidate Payload: {payload}")
            mcp_response = call_mcp_api(session, 'POST', '/candidate', json_payload=payload)

            if mcp_response and not mcp_response.get('error'):
                resp_cand_id = mcp_response.get('candidate', {}).get('candidate_id', candidate_id)
                logger.info(f"Successfully ingested/updated candidate: {name} (ID: {resp_cand_id})")
                ingested_count += 1
            else:
                logger.error(f"Failed to ingest candidate via MCP: {name}. MCP Response: {mcp_response}")
                failed_count += 1

            # Politeness delay to avoid overwhelming MCP server if it's busy
            time.sleep(0.05) # 50ms delay

        except Exception as row_error:
            logger.error(f"Error processing CSV row {row_num}: {row_error}", exc_info=True)
            failed_count += 1

    total_processed = ingested_count + failed_count + skipped_count
    logger.info(f"Finished candidate ingestion loop. Processed: {total_processed}, Succeeded: {ingested_count}, Failed: {failed_count}, Skipped: {skipped_count}.")

    # --- Trigger Relationship Creation ---
    if trigger_relationships and ingested_count > 0:
         logger.info("Attempting to trigger :SAME_STATE_AS relationship creation via MCP...")
         mcp_response = call_mcp_api(session, 'POST', '/admin/create_relationships/same_state')
         if mcp_response and not mcp_response.get('error'):
              logger.info(f"MCP Response for relationship trigger: {mcp_response.get('message', 'OK')}")
         else:
              logger.error(f"Failed to trigger relationship creation via MCP. Response: {mcp_response}")

    session.close()
    logger.info("MCP session closed.")
    return failed_count == 0 # Return True if all attempted rows ingested successfully


# --- Command Line Interface ---
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest candidate data from a CSV file via the Oppo MCP Server.")
    parser.add_argument("csv_file", help="Path to the input CSV file (e.g., gop_youtube.csv).")
    parser.add_argument(
        "--no-rels",
        action="store_true",
        help="Skip triggering the :SAME_STATE_AS relationship creation after ingestion."
    )
    parser.add_argument(
        '-v', '--verbose',
        action='store_const',
        dest='log_level_override', # Use different dest to avoid conflict if LOG_LEVEL imported
        const=logging.DEBUG,
        default=logging.INFO, # Default log level for script execution
        help='Enable verbose (DEBUG) logging for the script'
    )

    args = parser.parse_args()

    # Update log level if verbose flag is set by argument
    if args.log_level_override:
        logging.getLogger().setLevel(args.log_level_override)
        logger.setLevel(args.log_level_override)
        logger.info(f"Script log level set to DEBUG.")
        # Set requests/urllib3 back to WARNING if needed
        logging.getLogger("requests").setLevel(logging.WARNING)
        logging.getLogger("urllib3").setLevel(logging.WARNING)

    # Check prerequisites
    if not MCP_SERVER_URL:
        logger.critical("Error: MCP_SERVER_URL environment variable must be set.")
        sys.exit(1)
    if not os.path.exists(args.csv_file):
         logger.critical(f"Error: Input CSV file not found at '{args.csv_file}'")
         sys.exit(1)


    success = ingest_candidates_from_csv(args.csv_file, trigger_relationships=(not args.no_rels))

    if success:
        logger.info("CSV ingestion completed successfully.")
        sys.exit(0)
    else:
        logger.error("CSV ingestion completed with errors.")
        sys.exit(1)

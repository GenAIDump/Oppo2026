# File: Oppo/data_collection/scheduler.py
# Purpose: Schedules background data crawls (if enabled). Listener triggering is handled by listener_service.

import schedule
import time
import logging
import os
import requests # Needed if triggering MCP directly for background jobs
from typing import Dict, List, Callable, Optional

# Use config from a2a_host package
try:
    # Assumes config.py is available via PYTHONPATH or project structure
    from a2a_host.config import LOG_LEVEL, MCP_SERVER_URL, INTERNAL_SERVICE_API_KEY
    CONFIG_LOADED = True
except ImportError as e:
     # Basic config if run standalone or structure differs
     # Ensure logging is configured if this fails
     logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper(), format='%(asctime)s:%(levelname)s:%(name)s:%(lineno)d:%(message)s')
     logger = logging.getLogger(__name__) # Need logger instance here
     logger.warning(f"Could not import config from a2a_host ({e}). Using environment variables for scheduler.")
     LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
     MCP_SERVER_URL = os.getenv("MCP_SERVER_URL")
     INTERNAL_SERVICE_API_KEY = os.getenv("INTERNAL_SERVICE_API_KEY")
     CONFIG_LOADED = False # Mark that loading from config module failed

# Ensure logging is configured before use (again, safe if already done)
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format='%(asctime)s:%(levelname)s:%(name)s:%(lineno)d:%(message)s',
    force=True # Reconfigure if needed
)
logger = logging.getLogger(__name__)
logging.getLogger("schedule").setLevel(logging.WARNING) # Quieten schedule lib unless debugging


# --- Placeholder: Triggering Background Crawl/Processing Jobs via MCP ---
# This function represents triggering a job that would ideally run the crawler,
# processor, and then POST the structured data to appropriate MCP endpoints.
# This scheduler itself doesn't run the crawl/process logic directly anymore.

def trigger_background_job(source_name: str):
    """Placeholder function to represent triggering a background data collection job via MCP."""
    logger.info(f"--- Triggering Background Data Collection for: {source_name} (Placeholder) ---")
    if not MCP_SERVER_URL:
        logger.error(f"Cannot trigger background job for {source_name}: MCP_SERVER_URL not configured.")
        return

    # Example: Sending a POST request to an MCP endpoint to initiate the job
    mcp_trigger_endpoint = f"{MCP_SERVER_URL.rstrip('/')}/admin/trigger_crawl/{source_name}" # Endpoint needs implementation
    headers = {"Accept": "application/json"}
    if INTERNAL_SERVICE_API_KEY:
        headers["X-API-KEY"] = INTERNAL_SERVICE_API_KEY
    else:
        logger.warning(f"Triggering background job for {source_name} without internal API key.")

    try:
        # NOTE: The MCP endpoint '/admin/trigger_crawl/{source_name}' needs to be implemented
        # on the MCP server to actually start the background task (e.g., via a task queue like Celery).
        # response = requests.post(mcp_trigger_endpoint, headers=headers, timeout=15)
        # response.raise_for_status()
        # logger.info(f"Successfully triggered background job for {source_name} via MCP. Response: {response.json()}")
        logger.warning(f"Background job triggering for {source_name} is a placeholder. Requires MCP endpoint '/admin/trigger_crawl/' implementation to initiate the actual work.")
    except Exception as e:
        logger.error(f"Failed to trigger background job for {source_name} via MCP: {e}", exc_info=False)
    finally:
         logger.info(f"--- Finished Background Trigger attempt for: {source_name} ---")


# --- Schedule Setup ---
# Clear any existing schedule from previous runs if module is reloaded
schedule.clear()

# --- Listener Triggering Note ---
logger.info("Listener triggering is expected to be handled by the dedicated listener_service (listeners.listener_manager).")
logger.info("This scheduler is intended ONLY for background data collection jobs, if enabled.")


# --- Scheduling Background Crawl Jobs (Commented Out By Default for v0.1) ---
# Uncomment and configure if background data collection is actively used and scheduled from here.
# Ensure the trigger_background_job function interacts with a working MCP endpoint or task queue.

# logger.info("Scheduling background data collection jobs (currently commented out)...")
# schedule.every().day.at("03:00").tag("background-crawl").do(trigger_background_job, source_name="fec")
# schedule.every().day.at("03:30").tag("background-crawl").do(trigger_background_job, source_name="opensecrets")
# schedule.every(12).hours.tag("background-crawl").do(trigger_background_job, source_name="congress")
# schedule.every(6).hours.tag("background-crawl").do(trigger_background_job, source_name="house_press")
# schedule.every(2).days.at("04:00").tag("background-crawl").do(trigger_background_job, source_name="ballotpedia")
# schedule.every(3).days.at("04:30").tag("background-crawl").do(trigger_background_job, source_name="campaign_websites")


# --- Main Loop ---
def run_scheduler():
    """Runs the main scheduling loop ONLY IF this script is the designated scheduler for background jobs."""
    global running # Use global flag for signal handling
    running = True

    scheduled_jobs = schedule.get_jobs() # Check if any jobs were actually scheduled
    if not scheduled_jobs:
        logger.warning("No background jobs were uncommented or scheduled. Scheduler exiting.")
        return

    logger.info(f"Background Job Scheduler starting with {len(scheduled_jobs)} job(s) scheduled...")
    while running:
        try:
            n = schedule.idle_seconds()
            if n is None:
                # This happens if all jobs have been removed or marked as finished
                logger.info("No more scheduled jobs remaining in the queue.")
                break
            elif n > 0:
                # Sleep efficiently until the next job, check running flag periodically
                # Calculate sleep chunks to allow faster shutdown response
                wait_start = time.monotonic()
                while running and time.monotonic() - wait_start < n:
                     time.sleep(min(1.0, n - (time.monotonic() - wait_start))) # Sleep in 1s chunks or remaining time
            if not running: # Check flag again after sleep/wait
                 break
            logger.debug("Checking for pending scheduled jobs...")
            schedule.run_pending()
        except KeyboardInterrupt:
            # Signal handler should catch this ideally
            logger.info("Scheduler received KeyboardInterrupt in loop. Stopping...")
            running = False
        except Exception as e:
            logger.error(f"Error in scheduler loop: {e}", exc_info=True)
            # Avoid tight loop on unexpected error
            time.sleep(60)

    logger.info("Background Job Scheduler loop finished.")

# This main block is only relevant if this script is run directly as the scheduler
# for BACKGROUND jobs. Listener scheduling happens in listener_manager.py service.
if __name__ == "__main__":
    logger.warning("Running data_collection/scheduler.py directly.")
    logger.warning("Ensure this is intended, as listener scheduling is handled by listener_manager.py.")
    logger.warning("This script will only run scheduled BACKGROUND jobs if they are uncommented.")

    # Add signal handling if running as main process
    import signal
    running = True # Define flag for signal handler
    def handle_shutdown_signal(signum, frame):
        global running
        if running: # Prevent multiple shutdown messages
             print() # newline after ^C
             logger.info(f"Received signal {signal.Signals(signum).name}. Stopping background job scheduler...")
             running = False # Signal the loop to stop
    signal.signal(signal.SIGINT, handle_shutdown_signal)
    signal.signal(signal.SIGTERM, handle_shutdown_signal)

    run_scheduler()
    logger.info("Background Job Scheduler process finished.")

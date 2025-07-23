# File: Oppo/listeners/listener_manager.py
# Purpose: Orchestrates different listeners based on schedule and config fetched from MCP Server.

import schedule
import time
import threading
import requests
import logging
import os
from typing import Dict, List, Optional, Callable

# Use config from a2a_host package - assumes standard project structure
# Adjust relative path if necessary
try:
    # Assumes config.py is available within the execution environment path
    from a2a_host.config import (
        YOUTUBE_API_KEY, TELEGRAM_BOT_TOKEN,
        MCP_SERVER_URL, INTERNAL_SERVICE_API_KEY, LOG_LEVEL
    )
    CONFIG_LOADED = True
except ImportError as e:
     # Fallback for standalone use or different structure
     # Ensure logging is set up before first use
     log_level_env = os.getenv("LOG_LEVEL", "INFO").upper()
     logging.basicConfig(
         level=getattr(logging, log_level_env, logging.INFO),
         format='%(asctime)s - %(levelname)s - %(name)s - %(message)s'
     )
     logger = logging.getLogger(__name__) # Need logger instance here
     logger.warning(f"Could not import config from a2a_host ({e}). Loading URLs/Keys from environment for ListenerManager.")
     MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://localhost:8001")
     INTERNAL_SERVICE_API_KEY = os.getenv("INTERNAL_SERVICE_API_KEY")
     YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
     TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
     LOG_LEVEL = log_level_env
     CONFIG_LOADED = True # Assume loaded from env if import fails

# Import specific listener classes only if their libraries are available
_YT_LISTENER_ENABLED = False
_TG_LISTENER_ENABLED = False
try:
    from .youtube_listener import YouTubeListener
    if YouTubeListener.is_available(): # Add a class method to check dependency load
        _YT_LISTENER_ENABLED = True
except ImportError:
    pass # Logged within youtube_listener module already

try:
    from .telegram_listener import TelegramListener
    if TelegramListener.is_available(): # Add a class method to check dependency load
        _TG_LISTENER_ENABLED = True
except ImportError:
    pass # Logged within telegram_listener module already


# Ensure logging is configured before use (again, safe if already done)
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format='%(asctime)s:%(levelname)s:%(name)s:%(lineno)d:%(message)s', # Added lineno
    force=True # Reconfigure if needed
)
logger = logging.getLogger(__name__)

# Reduce noise from libraries
logging.getLogger("requests").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("schedule").setLevel(logging.INFO)


class ListenerManager:
    """
    Orchestrates listener tasks. Fetches configuration and state from the MCP Server,
    then dispatches checks to individual listeners (YouTube, Telegram).
    Intended to be run as a separate service.
    """
    def __init__(self):
        self.mcp_base_url = MCP_SERVER_URL
        self.api_key = INTERNAL_SERVICE_API_KEY
        self.session = requests.Session() # Session for MCP calls
        if not self.mcp_base_url:
             logger.critical("MCP_SERVER_URL not configured. Listener Manager cannot operate.")
             # Consider raising an error if MCP is essential
             raise ValueError("MCP_SERVER_URL must be configured.")

        if self.api_key:
            self.session.headers.update({"X-API-KEY": self.api_key, "Accept": "application/json"})
            logger.info("ListenerManager MCP client session initialized with API Key.")
        else:
            logger.warning("ListenerManager initialized without INTERNAL_SERVICE_API_KEY. MCP requests may fail authentication.")

        # Initialize listeners only if their keys/tokens are present AND libraries loaded
        self.youtube_listener = YouTubeListener(YOUTUBE_API_KEY) if _YT_LISTENER_ENABLED and YOUTUBE_API_KEY else None
        self.telegram_listener = TelegramListener(TELEGRAM_BOT_TOKEN) if _TG_LISTENER_ENABLED and TELEGRAM_BOT_TOKEN else None
        self.running = True
        self.threads: List[threading.Thread] = [] # Keep track of active threads
        # Use a lock for thread-safe access to shared resources if any (e.g., self.threads)
        self._thread_lock = threading.Lock()
        logger.info(f"ListenerManager initialized targeting MCP at {self.mcp_base_url}.")
        if not self.youtube_listener: logger.warning("YouTube listener disabled (check API key and googleapiclient library).")
        if not self.telegram_listener: logger.warning("Telegram listener disabled (check Bot token and python-telegram-bot library).")

    def _fetch_mcp_data(self, endpoint: str, params: Optional[Dict] = None) -> Optional[Any]:
        """Helper to fetch data from MCP server with standard error handling."""
        if not self.mcp_base_url: return None
        url = f"{self.mcp_base_url.rstrip('/')}/{endpoint.lstrip('/')}"
        try:
            # Use headers from session which include API key if configured
            response = self.session.get(url, params=params, timeout=30) # Increased timeout
            response.raise_for_status() # Raise HTTPError for 4xx/5xx responses
            data = response.json()
            if isinstance(data, dict) and data.get("status") == "success":
                logger.debug(f"MCP Response Success for GET {endpoint}")
                return data # Return full success response dict
            elif isinstance(data, dict): # MCP returned a structured error
                 error_msg = data.get('message', data.get('detail', 'Unknown MCP error structure'))
                 logger.error(f"MCP Error fetching {endpoint}: {error_msg}")
                 return None # Return None on logical error from MCP
            else:
                 logger.error(f"Unexpected MCP response format from {endpoint}: {str(data)[:200]}")
                 return None

        except requests.exceptions.Timeout:
             logger.error(f"Timeout fetching from MCP endpoint: {endpoint}")
             return None
        except requests.exceptions.HTTPError as e:
             logger.error(f"HTTP Error fetching from MCP endpoint {endpoint}: {e.response.status_code} {e.response.text[:200]}", exc_info=False)
             return None
        except requests.exceptions.RequestException as e:
            logger.error(f"Network Error fetching from MCP endpoint {endpoint}: {e}", exc_info=False)
            return None
        except Exception as e:
             logger.error(f"Unexpected error fetching MCP data from {endpoint}: {e}", exc_info=True)
             return None

    def _run_listener_check_threaded(self, listener_instance, check_method_name: str, candidate_id: str, channel_id: str, state: Optional[Dict]):
        """Runs a specific listener check method safely in a thread."""
        if not listener_instance:
            logger.warning(f"Attempted check '{check_method_name}' but listener instance is None (Cand: {candidate_id}).")
            return
        thread_name = f"{check_method_name}-{candidate_id}-{str(channel_id)[:15]}"
        threading.current_thread().name = thread_name
        try:
            check_method = getattr(listener_instance, check_method_name)
            logger.info(f"Thread {thread_name}: Starting check...")
            # Pass state dict directly
            check_method(candidate_id=candidate_id, channel_identifier=channel_id, listener_state=state)
            logger.info(f"Thread {thread_name}: Check finished.")
        except AttributeError:
             logger.error(f"Thread {thread_name}: Listener instance {type(listener_instance).__name__} missing method '{check_method_name}'")
        except Exception as e:
            # Catch errors within the thread to prevent manager crash
            logger.error(f"Thread {thread_name}: Unhandled error during check: {e}", exc_info=True)
        finally:
             # Remove thread from active list when done (optional cleanup)
             with self._thread_lock:
                  # Find and remove the completed thread object
                  # This might be slightly inefficient if list is very large
                  current_thread = threading.current_thread()
                  self.threads = [t for t in self.threads if t is not current_thread]
                  logger.debug(f"Thread {thread_name} finished and removed from active list. Active: {len(self.threads)}")


    def _fetch_and_dispatch(self, platform: str, listener_instance, check_method_name: str):
        """Fetches candidates and states for a platform via MCP, then dispatches checks in threads."""
        if not listener_instance:
            logger.info(f"Skipping {platform} checks: Listener not initialized.")
            return

        logger.info(f"Fetching candidates configured for {platform} listener via MCP...")
        # MCP endpoint returns {'status':'success', 'candidates': [list of Candidate models as dicts]}
        # Candidate dicts should contain candidate_id and the relevant channel_id property
        candidates_response = self._fetch_mcp_data(f"/candidates/listeners/{platform}")

        if not candidates_response or not isinstance(candidates_response.get('candidates'), list):
            logger.error(f"Failed to fetch or parse candidate list for {platform} from MCP.")
            return

        candidates = candidates_response['candidates']
        if not candidates:
            logger.info(f"No candidates configured in DB for {platform} listener.")
            return

        logger.info(f"Found {len(candidates)} candidate(s) for {platform} checks. Fetching states and dispatching...")
        dispatched_count = 0
        # Clean up completed threads before starting new ones
        with self._thread_lock:
            self.threads = [t for t in self.threads if t.is_alive()]
            logger.debug(f"Currently {len(self.threads)} active listener threads before dispatch.")

        # Maximum concurrent listener threads (adjust based on resources/API limits)
        MAX_CONCURRENT_CHECKS = int(os.getenv("LISTENER_MAX_CONCURRENCY", 10))
        active_threads_semaphore = threading.Semaphore(MAX_CONCURRENT_CHECKS)
        dispatch_threads = [] # Keep track of threads started in this batch

        for candidate in candidates:
            candidate_id = candidate.get('candidate_id')
            # Property name matches platform name used in URL and model
            channel_id = candidate.get(f"{platform}_channel_id")

            if not candidate_id or not channel_id:
                logger.warning(f"Skipping candidate due to missing 'candidate_id' or '{platform}_channel_id': {candidate.get('name', 'N/A')}")
                continue

            # Fetch the last state for this specific candidate and platform
            state_response = self._fetch_mcp_data(f"/listener_state/{candidate_id}/{platform}")
            # Get the 'state' dict, default to empty dict if fetch failed or state is null/missing
            listener_state = state_response.get('state') if isinstance(state_response, dict) and isinstance(state_response.get('state'), dict) else {}

            logger.debug(f"Dispatching {platform} check for Cand:{candidate_id} Chan:{channel_id} State:{listener_state}")

            # Acquire semaphore before starting thread
            if not active_threads_semaphore.acquire(timeout=5): # Add timeout
                logger.warning(f"Timeout acquiring semaphore for {platform} check (Cand:{candidate_id}). Skipping dispatch.")
                continue

            # Define a wrapper to release the semaphore when the thread finishes
            def thread_target_wrapper(listener, method_name, c_id, ch_id, state_dict):
                try:
                    self._run_listener_check_threaded(listener, method_name, c_id, ch_id, state_dict)
                finally:
                    try:
                        active_threads_semaphore.release()
                        # logger.debug(f"Semaphore released by thread for Cand:{c_id} Chan:{str(ch_id)[:15]}")
                    except ValueError: # Avoid crashing if released too many times
                        logger.error(f"Error releasing semaphore for Cand:{c_id} Chan:{str(ch_id)[:15]} - already released?")


            # Dispatch the check in a new thread using the wrapper
            thread = threading.Thread(
                target=thread_target_wrapper,
                args=(listener_instance, check_method_name, candidate_id, channel_id, listener_state),
                daemon=True # Allow main thread to exit even if these are running
            )
            dispatch_threads.append(thread) # Add to batch list
            thread.start()
            dispatched_count += 1

        # Add newly started threads to the main list
        with self._thread_lock:
            self.threads.extend(dispatch_threads)

        logger.info(f"Dispatched {dispatched_count} {platform} checks.")
        # Note: Threads run in the background.

    def check_youtube_channels(self):
        """Fetches YouTube channels from MCP and triggers checks."""
        if not self.youtube_listener:
             logger.debug("Skipping YouTube check cycle - listener disabled.")
             return
        logger.info("=== Starting YouTube Check Cycle ===")
        self._fetch_and_dispatch('youtube', self.youtube_listener, 'check_channel')
        logger.info("=== Finished YouTube Check Cycle Dispatch ===")


    def check_telegram_channels(self):
        """Fetches Telegram channels from MCP and triggers checks."""
        if not self.telegram_listener:
             logger.debug("Skipping Telegram check cycle - listener disabled.")
             return
        logger.info("=== Starting Telegram Check Cycle ===")
        self._fetch_and_dispatch('telegram', self.telegram_listener, 'check_channel')
        logger.info("=== Finished Telegram Check Cycle Dispatch ===")


    def run_schedule(self):
        """Runs the main scheduling loop for triggering listener checks."""
        logger.info("Starting ListenerManager schedule...")

        # Configure schedule - adjust intervals as needed
        youtube_job_scheduled = False
        if self.youtube_listener:
            schedule.every(15).to(25).minutes.do(self.check_youtube_channels)
            logger.info("Scheduled YouTube checks every 15-25 minutes.")
            youtube_job_scheduled = True

        telegram_job_scheduled = False
        if self.telegram_listener:
            schedule.every(5).to(10).minutes.do(self.check_telegram_channels)
            logger.info("Scheduled Telegram checks every 5-10 minutes.")
            telegram_job_scheduled = True

        if not youtube_job_scheduled and not telegram_job_scheduled:
            logger.critical("No listener jobs could be scheduled (check API keys/tokens and listener initialization). Listener Manager cannot run checks.")
            self.running = False
            return

        # Run initial check immediately after starting (optional)
        logger.info("Running initial listener checks dispatch...")
        if youtube_job_scheduled:
             threading.Thread(target=self.check_youtube_channels, daemon=True).start()
        if telegram_job_scheduled:
             threading.Thread(target=self.check_telegram_channels, daemon=True).start()
        logger.info("Initial checks dispatched.")


        while self.running:
            try:
                 n = schedule.idle_seconds()
                 if n is None:
                     logger.warning("No more pending scheduled jobs found? Listener Manager check loop may be misconfigured.")
                     time.sleep(60) # Sleep before checking again
                     continue
                 elif n > 0:
                     # Sleep efficiently until the next job, check running flag periodically
                     wait_start = time.monotonic()
                     while self.running and time.monotonic() - wait_start < n:
                         time.sleep(min(1.0, n - (time.monotonic() - wait_start))) # Sleep in 1s chunks

                 if not self.running: break # Exit if stop signal received during sleep

                 logger.debug("Checking for pending scheduled listener jobs...")
                 schedule.run_pending()
            except KeyboardInterrupt:
                 logger.info("KeyboardInterrupt caught in Listener Manager scheduler loop.")
                 self.stop()
            except Exception as e:
                 logger.error(f"Error in Listener Manager scheduling loop: {e}", exc_info=True)
                 time.sleep(60) # Avoid tight loop on error

        logger.info("ListenerManager scheduling loop finished.")


    def stop(self):
        """Stops the scheduling loop and attempts cleanup."""
        if not self.running: # Prevent multiple stop calls
            return
        logger.info("Stopping ListenerManager...")
        self.running = False
        schedule.clear() # Stop scheduled jobs from running further
        # Wait briefly for active threads? (Optional, daemons might exit abruptly)
        with self._thread_lock:
            active_thread_count = sum(1 for t in self.threads if t.is_alive())
        if active_thread_count > 0:
            logger.info(f"Waiting up to 10 seconds for {active_thread_count} active listener threads to finish...")
            join_timeout = 10.0
            start_join = time.monotonic()
            # Create copy of thread list to avoid modification issues during iteration
            threads_to_join = []
            with self._thread_lock:
                threads_to_join = self.threads[:]

            for thread in threads_to_join:
                if thread.is_alive():
                     remaining_time = join_timeout - (time.monotonic() - start_join)
                     if remaining_time > 0:
                          thread.join(timeout=remaining_time)
                     else:
                          logger.warning("Timeout expired while waiting for listener threads.")
                          break # Timeout expired
        logger.info("ListenerManager stopped.")

# --- Main Execution ---
# This allows running the Listener Manager as a standalone process/service
# Triggered by the command in docker-compose.yml
if __name__ == "__main__":
    # Ensure config is loaded if run directly
    if not CONFIG_LOADED:
         logger.warning("Running listener_manager directly without importing config successfully. Relying solely on environment variables.")

    manager = ListenerManager()
    if not manager.youtube_listener and not manager.telegram_listener:
         logger.critical("Neither YouTube nor Telegram listeners are configured. Exiting Listener Manager.")
    else:
        # Add signal handling for graceful shutdown (SIGTERM from Docker, SIGINT from Ctrl+C)
        import signal
        def handle_signal(signum, frame):
             print() # Newline after ^C
             logger.info(f"Received signal {signal.Signals(signum).name}. Shutting down Listener Manager gracefully...")
             # Trigger the stop method which sets self.running = False
             if manager:
                  manager.stop()

        signal.signal(signal.SIGINT, handle_signal)
        signal.signal(signal.SIGTERM, handle_signal)

        logger.info("Listener Manager process started. Press Ctrl+C to stop.")
        try:
            manager.run_schedule() # This blocks until manager.running is False or loop exits
        except Exception as e:
             logger.critical(f"Listener Manager main loop exited unexpectedly: {e}", exc_info=True)
        finally:
             # Ensure stop is called again in case loop exited abruptly
             if manager and manager.running:
                  manager.stop()
             logger.info("Listener Manager process finished.")

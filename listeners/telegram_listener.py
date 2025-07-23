# File: Oppo/listeners/telegram_listener.py
# Purpose: Polls Telegram Bot API for new messages in specified channels.

import logging
import requests # To send data to A2A Host and MCP Server
import time
import os
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List

# Use config from a2a_host package
try:
    from a2a_host.config import (
         A2A_HOST_INTERNAL_URL, A2A_HOST_INGEST_ENDPOINT,
         MCP_SERVER_URL, INTERNAL_SERVICE_API_KEY, LOG_LEVEL,
         TELEGRAM_BOT_TOKEN # Explicitly import token
    )
    CONFIG_LOADED = True
except ImportError as e:
     # Fallback for standalone use or different structure
     logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(name)s - %(message)s')
     logger = logging.getLogger(__name__) # Need logger instance here
     logger.warning(f"Could not import config from a2a_host ({e}). Loading URLs/Keys from environment for TelegramListener.")
     MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://localhost:8001")
     A2A_HOST_INTERNAL_URL = os.getenv("A2A_HOST_INTERNAL_URL", "http://localhost:8000")
     A2A_HOST_INGEST_ENDPOINT = "/ingest/social_post" # Default
     INTERNAL_SERVICE_API_KEY = os.getenv("INTERNAL_SERVICE_API_KEY")
     TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
     LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
     CONFIG_LOADED = True # Assume loaded from env if import fails

# Import Telegram Bot library
try:
    from telegram import Bot, Update # Import Update for type hinting if needed
    # from telegram.constants import ParseMode # If needed for formatting later
    from telegram.error import TelegramError, NetworkError, RetryAfter, TimedOut, BadRequest
    TELEGRAM_LIB_LOADED = True
except ImportError:
    logging.error("python-telegram-bot library not found. Telegram listener functionality disabled. Install with: pip install python-telegram-bot")
    TELEGRAM_LIB_LOADED = False
    TelegramError = NetworkError = RetryAfter = TimedOut = BadRequest = Exception # Dummy exceptions
    Bot = object # Dummy object
    Update = object # Dummy object


# Ensure logging is configured before use
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format='%(asctime)s:%(levelname)s:%(name)s:%(lineno)d:%(message)s'
)
logger = logging.getLogger(__name__)

# Construct target URLs only if base URLs are set
INGESTION_URL = None
if A2A_HOST_INTERNAL_URL and A2A_HOST_INGEST_ENDPOINT:
    INGESTION_URL = f"{A2A_HOST_INTERNAL_URL.rstrip('/')}{A2A_HOST_INGEST_ENDPOINT.lstrip('/')}"
else:
    logger.error("TelegramListener: A2A_HOST_INTERNAL_URL or A2A_HOST_INGEST_ENDPOINT not configured. Ingestion disabled.")

MCP_LISTENER_STATE_URL = None
if MCP_SERVER_URL:
     MCP_LISTENER_STATE_URL = f"{MCP_SERVER_URL.rstrip('/')}/listener_state"
else:
     logger.error("TelegramListener: MCP_SERVER_URL not configured. Cannot get/update listener state.")


class TelegramListener:
    """Polls Telegram channels using Bot API getUpdates for new messages."""
    def __init__(self, bot_token: Optional[str]):
        """
        Initializes the TelegramListener.
        Args:
            bot_token: The Telegram Bot API token. Can be None to disable.
        """
        self.bot_token = bot_token
        self.bot: Optional[Bot] = None
        self.session = requests.Session() # For calling MCP and Ingestion API
        if INTERNAL_SERVICE_API_KEY:
            self.session.headers.update({"X-API-KEY": INTERNAL_SERVICE_API_KEY, "Accept": "application/json"})
            logger.debug("TelegramListener internal requests session initialized with API Key.")
        else:
            logger.warning("TelegramListener running without internal API key. MCP/Ingestion calls might fail auth.")

        if TELEGRAM_LIB_LOADED and self.bot_token:
            try:
                self.bot = Bot(token=self.bot_token)
                # Test connection by getting bot info - wrap in try/except
                # This can block, consider doing it async or just logging success
                try:
                     bot_info = self.bot.get_me()
                     logger.info(f"Telegram client initialized successfully for bot: @{bot_info.username}")
                except TelegramError as e:
                     logger.error(f"Telegram bot get_me failed (check token/network): {e}")
                     self.bot = None # Mark as failed
            except ValueError as e: # Handle potential invalid token format early
                 logger.error(f"Invalid Telegram Bot Token format: {e}")
                 self.bot = None
            except Exception as e:
                logger.error(f"Unexpected error initializing Telegram bot client: {e}", exc_info=True)
                self.bot = None
        elif not TELEGRAM_LIB_LOADED:
             logger.error("TelegramListener disabled: python-telegram-bot library not loaded.")
        else: # Bot token missing
             logger.error("TelegramListener disabled: Telegram Bot Token missing or not provided during init.")

    def _update_listener_state_mcp(self, candidate_id: str, platform: str, state: dict) -> bool:
        """Updates listener state via MCP Server."""
        if not MCP_LISTENER_STATE_URL:
             logger.error(f"Cannot update state for Cand:{candidate_id} Platform:{platform}: MCP_SERVER_URL not configured.")
             return False
        # Ensure state contains valid integer for update_id if present
        if 'last_update_id' in state and not isinstance(state['last_update_id'], int):
             logger.error(f"Invalid type for last_update_id in state: {state['last_update_id']}")
             return False

        url = f"{MCP_LISTENER_STATE_URL}/{candidate_id}"
        payload = {"platform": platform, "state": state}
        logger.debug(f"Attempting to update listener state via MCP: PUT {url} Payload: {payload}")
        try:
            response = self.session.put(url, json=payload, timeout=15)
            response.raise_for_status()
            logger.info(f"Successfully updated listener state via MCP for Cand:{candidate_id} Platform:{platform} State:{state}")
            return True
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to update listener state via MCP for Cand:{candidate_id} Platform:{platform}: {e}", exc_info=False)
            if e.response is not None:
                logger.error(f"MCP Update State Response: {e.response.status_code} {e.response.text[:200]}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error updating listener state via MCP: {e}", exc_info=True)
            return False

    def _send_to_ingestion(self, post_data: dict) -> bool:
        """Sends formatted post data to the A2A Host ingestion endpoint."""
        if not INGESTION_URL:
             logger.error(f"Cannot ingest post {post_data.get('post_id')}: Ingestion URL not configured.")
             return False
        try:
            # Ensure timestamp is ISO format string before sending JSON
            if isinstance(post_data.get('timestamp'), datetime):
                 ts = post_data['timestamp']
                 if ts.tzinfo is None: ts = ts.replace(tzinfo=timezone.utc)
                 post_data['timestamp'] = ts.isoformat(timespec='seconds').replace('+00:00', 'Z')
            elif isinstance(post_data.get('timestamp'), str):
                 if not ('T' in post_data['timestamp'] and ('Z' in post_data['timestamp'] or '+' in post_data['timestamp'])):
                     logger.warning(f"Timestamp string '{post_data['timestamp']}' might not be ISO format for ingestion.")

            # Ensure raw_data is serializable (convert complex Telegram objects if necessary)
            if 'raw_data' in post_data and not isinstance(post_data['raw_data'], (dict, list, str, int, float, bool, type(None))):
                 logger.warning(f"Raw data for post {post_data.get('post_id')} is complex type {type(post_data['raw_data'])}, attempting dict conversion.")
                 try:
                      # Example: Use to_dict() if it's a telegram object, otherwise convert to string
                      if hasattr(post_data['raw_data'], 'to_dict'):
                           post_data['raw_data'] = post_data['raw_data'].to_dict()
                      else:
                           post_data['raw_data'] = str(post_data['raw_data'])
                 except Exception as serial_err:
                      logger.error(f"Could not serialize raw_data for post {post_data.get('post_id')}: {serial_err}")
                      post_data['raw_data'] = {"error": "serialization failed"}


            logger.debug(f"Sending post {post_data.get('post_id')} to ingestion URL: {INGESTION_URL}")
            response = self.session.post(INGESTION_URL, json=post_data, timeout=30)
            response.raise_for_status() # Check for 4xx/5xx errors
            logger.info(f"Successfully ingested post {post_data.get('post_id')} from {post_data.get('source_platform')}")
            return True
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to ingest post {post_data.get('post_id')} to A2A Host: {e}", exc_info=False)
            if e.response is not None:
                 logger.error(f"Ingestion Response: {e.response.status_code} {e.response.text[:200]}")
            return False
        except Exception as e:
             logger.error(f"Unexpected error during ingestion call for post {post_data.get('post_id')}: {e}", exc_info=True)
             return False

    def check_channel(self, candidate_id: str, channel_identifier: str, listener_state: Optional[Dict]):
        """
        Checks a specific Telegram channel for new messages using getUpdates.
        Relies on the bot being a member of the channel OR the channel being public
        (though Bot API might still require membership for getUpdates).

        Args:
            candidate_id: Stable ID of the candidate.
            channel_identifier: Telegram channel ID (numeric, usually negative) or '@username'.
            listener_state: Dict containing {'last_update_id': int} or None.
        """
        if not self.bot:
            logger.error(f"Telegram bot client not available, cannot check channel {channel_identifier} for candidate {candidate_id}")
            return

        # Ensure listener_state is a dict, even if empty
        listener_state = listener_state or {}
        last_update_id = listener_state.get('last_update_id')
        start_time = time.time()
        logger.info(f"Checking Telegram channel '{channel_identifier}' for Cand:{candidate_id} / LastUpdateID:{last_update_id}")

        # `getUpdates` requires an offset one higher than the last received update_id
        offset = (last_update_id + 1) if isinstance(last_update_id, int) else None
        new_messages_processed_count = 0
        # Track the highest update ID *received* in this API call batch
        highest_update_id_received = None
        ingestion_error_occurred = False
        api_error_occurred = False


        try:
            # Use a reasonable timeout for long polling
            # Filter for channel_post updates only
            updates: List[Update] = self.bot.get_updates(
                offset=offset,
                timeout=25, # Long polling timeout
                limit=100, # Max limit
                allowed_updates=['channel_post']
            )

            logger.debug(f"Received {len(updates)} update(s) for offset {offset}. Checking for channel '{channel_identifier}'.")

            if not updates:
                logger.debug(f"No new relevant updates found for offset {offset}.")
                # No state update needed if no updates received at all
                highest_update_id_received = last_update_id # Ensure state doesn't regress
                # Note: Important NOT to return here, must proceed to state update logic below
                # to handle the case where highest_update_id_received remains unchanged.

            for update in updates:
                # Always track the highest update ID received from the API response
                current_update_id = update.update_id
                if highest_update_id_received is None or current_update_id > highest_update_id_received:
                     highest_update_id_received = current_update_id

                # Check if it's a channel post and matches the target channel
                # Ensure update.channel_post exists before accessing its attributes
                if update.channel_post and update.channel_post.chat:
                    message = update.channel_post
                    chat = message.chat
                    # Convert channel_identifier to string for reliable comparison
                    target_id_str = str(channel_identifier).strip()
                    chat_id_str = str(chat.id)
                    chat_username_lower = chat.username.lower() if chat.username else None
                    target_username_lower = target_id_str[1:].lower() if target_id_str.startswith('@') else None

                    matches_identifier = False
                    # Check if numeric chat ID matches
                    if chat_id_str == target_id_str:
                         matches_identifier = True
                    # Check if chat username matches (case-insensitive)
                    elif target_username_lower and chat_username_lower == target_username_lower:
                        matches_identifier = True

                    if matches_identifier:
                        logger.info(f"Processing relevant channel post UpdateID:{update.update_id} MsgID:{message.message_id} from Channel:'{channel_identifier}'")

                        timestamp_dt = message.date # Already datetime object (assume UTC if naive)
                        if timestamp_dt.tzinfo is None:
                             timestamp_dt = timestamp_dt.replace(tzinfo=timezone.utc)

                        # Construct URL
                        msg_link = f"https://t.me/{chat.username}/{message.message_id}" if chat.username else None

                        # Get content (text or caption for media)
                        content = message.text or message.caption or f"[Media Type: {message.effective_attachment.__class__.__name__}]" if message.effective_attachment else "[Empty Message]"

                        # Skip empty messages? Optional.
                        if content == "[Empty Message]":
                             logger.debug(f"Skipping empty message {message.message_id} from {channel_identifier}")
                             continue

                        post_data = {
                            "candidate_id": candidate_id,
                            "source_platform": "Telegram",
                            "post_id": f"{chat.id}_{message.message_id}", # Use chat_id + message_id
                            "post_composite_id": f"Telegram_{chat.id}_{message.message_id}", # For DB constraint
                            "content": content,
                            "timestamp": timestamp_dt, # Pass datetime object
                            "url": msg_link,
                            "author_username": chat.username or str(chat.id),
                            "raw_data": message.to_dict(), # Store raw message object dict
                        }

                        # Send to ingestion endpoint
                        if self._send_to_ingestion(post_data):
                            new_messages_processed_count += 1
                        else:
                            ingestion_error_occurred = True
                            logger.error(f"Stopping processing for channel {channel_identifier} check due to ingestion error. Last processed update ID remains {last_update_id}.")
                            highest_update_id_received = last_update_id # Prevent state update
                            break # Stop processing further updates in this batch

                    # else: logger.debug(f"Skipping message from non-target channel: {chat.id}/{chat.username}")
                # else: logger.debug(f"Skipping non-channel_post update type: {update.to_dict()}")


        except TimedOut:
             logger.debug(f"Telegram getUpdates timed out for offset {offset} (no new messages received within timeout).")
             highest_update_id_received = last_update_id # No change in state if timeout
        except RetryAfter as e:
             logger.warning(f"Telegram Flood control: need to wait {e.retry_after} seconds for channel {channel_identifier}. Check will retry later.")
             # Let the scheduler handle the backoff, do not update state
             highest_update_id_received = last_update_id
        except NetworkError as e:
             logger.error(f"Telegram NetworkError checking channel {channel_identifier}: {e}. Check connection.")
             api_error_occurred = True # Treat as critical error for state update
        except BadRequest as e:
             logger.error(f"Telegram BadRequest checking channel {channel_identifier} (Offset: {offset}): {e}. Bot removed? Offset too old? Invalid Channel ID?")
             # If offset is too old, getUpdates might return a 400 error.
             # Need a strategy to handle this, e.g., resetting offset? Or logging and manual intervention.
             # For now, just log and prevent state update.
             api_error_occurred = True
        except TelegramError as e:
            logger.error(f"Telegram API error checking channel {channel_identifier} (Offset: {offset}): {e}", exc_info=False)
            if "Unauthorized" in str(e):
                 logger.error(f"Bot may not have access to channel {channel_identifier} or token is invalid.")
            api_error_occurred = True # Treat as critical error for state update
        except Exception as e:
            logger.error(f"An unexpected error occurred checking channel {channel_identifier}: {e}", exc_info=True)
            api_error_occurred = True # Treat as critical error for state update


        # --- Update Listener State ---
        # Update state via MCP *only if* no critical API/Ingestion errors occurred
        # AND the highest received update ID is newer than the last known ID.
        if not api_error_occurred and not ingestion_error_occurred:
            if highest_update_id_received is not None and highest_update_id_received != last_update_id:
                 logger.info(f"Updating last update ID via MCP for Cand:{candidate_id} (Telegram) to {highest_update_id_received}")
                 update_success = self._update_listener_state_mcp(candidate_id, 'telegram', {'last_update_id': highest_update_id_received})
                 if not update_success:
                      logger.error(f"FAILED to update listener state via MCP for Cand:{candidate_id}, Platform:telegram after successful check.")
            else:
                 # This case means either no updates were found, or updates were old/same, or an error prevented processing relevant updates.
                 logger.info(f"No new Telegram updates processed requiring state update for channel {channel_identifier} since offset {offset}.")
        else:
             logger.warning(f"Skipping listener state update for channel {channel_identifier} due to API or Ingestion errors during check.")


        duration = time.time() - start_time
        logger.info(f"Finished checking Telegram channel {channel_identifier}. Processed {new_messages_processed_count} new messages in {duration:.2f}s.")

# File: Oppo/listeners/youtube_listener.py
# Purpose: Polls YouTube Data API for new videos and sends them for ingestion via A2A Host.

import logging
import requests # To send data to A2A Host and MCP Server
import isodate # To parse duration ISO 8601 format
import os
import json
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional

# Use config from a2a_host package - assumes standard project structure
try:
    from a2a_host.config import (
        A2A_HOST_INTERNAL_URL, A2A_HOST_INGEST_ENDPOINT,
        MCP_SERVER_URL, INTERNAL_SERVICE_API_KEY, LOG_LEVEL,
        YOUTUBE_API_KEY # Explicitly import YT Key
    )
    CONFIG_LOADED = True
except ImportError as e:
     # Fallback for standalone use or different structure
     logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(name)s - %(message)s')
     logger = logging.getLogger(__name__) # Need logger instance here
     logger.warning(f"Could not import config from a2a_host ({e}). Loading URLs/Keys from environment for YouTubeListener.")
     MCP_SERVER_URL = os.getenv("MCP_SERVER_URL", "http://localhost:8001")
     A2A_HOST_INTERNAL_URL = os.getenv("A2A_HOST_INTERNAL_URL", "http://localhost:8000")
     A2A_HOST_INGEST_ENDPOINT = "/ingest/social_post" # Default
     INTERNAL_SERVICE_API_KEY = os.getenv("INTERNAL_SERVICE_API_KEY")
     YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")
     LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
     CONFIG_LOADED = True # Assume loaded from env if import fails

# Import Google API client library
try:
    from googleapiclient.discovery import build
    from googleapiclient.errors import HttpError
    GOOGLE_API_LOADED = True
except ImportError:
    logging.error("google-api-python-client not found. YouTube listener functionality disabled. Install with: pip install google-api-python-client")
    GOOGLE_API_LOADED = False
    HttpError = Exception # Dummy exception
    build = object # Dummy object

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
    logger.error("A2A_HOST_INTERNAL_URL or A2A_HOST_INGEST_ENDPOINT not configured. Ingestion disabled.")

MCP_LISTENER_STATE_URL = None
if MCP_SERVER_URL:
     MCP_LISTENER_STATE_URL = f"{MCP_SERVER_URL.rstrip('/')}/listener_state"
else:
     logger.error("MCP_SERVER_URL not configured. Cannot get/update listener state.")


# --- Placeholder for Transcript Generation ---
# In a real system, this would involve calling a Speech-to-Text API (like Google Cloud Speech-to-Text)
# or using an ML model (like Whisper). This requires downloading the audio stream first.
# This function is a placeholder and returns None.
def _get_youtube_transcript(video_id: str) -> Optional[str]:
    """Placeholder function to represent fetching/generating a video transcript."""
    logger.warning(f"Transcript generation for video {video_id} is not implemented (placeholder). Returning None.")
    # Future implementation:
    # 1. Use youtube-dlp or similar to get audio stream URL (check ToS implications)
    # 2. Download audio
    # 3. Call Speech-to-Text API/model (e.g., Google Cloud Speech, Whisper)
    # 4. Return transcript text
    return None # Placeholder returns nothing

class YouTubeListener:
    """Polls YouTube channels for new videos and sends them for ingestion."""
    def __init__(self, api_key: Optional[str]):
        """
        Initializes the YouTubeListener.
        Args:
            api_key: The YouTube Data API v3 key. Can be None to disable the listener.
        """
        self.api_key = api_key
        self.youtube = None
        self.session = requests.Session() # For calling MCP and Ingestion API
        if INTERNAL_SERVICE_API_KEY:
            self.session.headers.update({"X-API-KEY": INTERNAL_SERVICE_API_KEY, "Accept": "application/json"})
            logger.debug("YouTubeListener internal requests session initialized with API Key.")
        else:
            logger.warning("YouTubeListener running without internal API key. MCP/Ingestion calls might fail auth.")

        if GOOGLE_API_LOADED and self.api_key:
            try:
                # cache_discovery=False prevents potential issues with stale discovery documents
                # Consider adding credentials for quota increases if using OAuth? For simple key, just developerKey.
                self.youtube = build('youtube', 'v3', developerKey=self.api_key, cache_discovery=False)
                logger.info("YouTube client initialized successfully.")
            except Exception as e:
                logger.error(f"Failed to initialize YouTube client: {e}", exc_info=True)
                self.youtube = None
        elif not GOOGLE_API_LOADED:
             logger.error("YouTubeListener disabled: google-api-python-client library not loaded.")
        else: # API key missing
             logger.error("YouTubeListener disabled: YouTube API Key missing or not provided during init.")


    def _update_listener_state_mcp(self, candidate_id: str, platform: str, state: dict) -> bool:
        """Updates listener state via MCP Server."""
        if not MCP_LISTENER_STATE_URL:
             logger.error(f"Cannot update state for Cand:{candidate_id} Platform:{platform}: MCP_SERVER_URL not configured.")
             return False
        # Ensure the state being sent is valid JSON (e.g., datetime is ISO string)
        if 'last_checked_timestamp' in state and isinstance(state['last_checked_timestamp'], datetime):
             state['last_checked_timestamp'] = state['last_checked_timestamp'].isoformat()

        url = f"{MCP_LISTENER_STATE_URL}/{candidate_id}"
        payload = {"platform": platform, "state": state}
        logger.debug(f"Attempting to update listener state via MCP: PUT {url} Payload: {payload}")
        try:
            response = self.session.put(url, json=payload, timeout=15)
            response.raise_for_status() # Check for 4xx/5xx errors
            # Optionally check response body for confirmation if MCP returns one
            # data = response.json()
            # if data.get('status') != 'success':
            #    logger.error(f"MCP server returned non-success on state update: {data}")
            #    return False
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
                 # Ensure UTC 'Z' format for consistency if possible
                 ts = post_data['timestamp']
                 if ts.tzinfo is None: ts = ts.replace(tzinfo=timezone.utc)
                 post_data['timestamp'] = ts.isoformat(timespec='seconds').replace('+00:00', 'Z')
            elif isinstance(post_data.get('timestamp'), str):
                # Basic check if it already looks like ISO format
                if not ('T' in post_data['timestamp'] and ('Z' in post_data['timestamp'] or '+' in post_data['timestamp'])):
                     logger.warning(f"Timestamp string '{post_data['timestamp']}' might not be ISO format for ingestion.")


            logger.debug(f"Sending post {post_data.get('post_id')} to ingestion URL: {INGESTION_URL}")
            response = self.session.post(INGESTION_URL, json=post_data, timeout=30)
            response.raise_for_status() # Check for 4xx/5xx errors
            # Optionally check response body
            # data = response.json()
            # if not data or data.get('post_node_id') is None:
            #     logger.error(f"Ingestion endpoint did not return expected confirmation for post {post_data.get('post_id')}. Response: {data}")
            #     return False
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


    def get_channel_uploads_playlist_id(self, channel_id: str) -> Optional[str]:
        """Gets the uploads playlist ID for a given channel ID."""
        if not self.youtube:
             logger.error("YouTube client not initialized, cannot get uploads playlist.")
             return None
        logger.debug(f"Fetching uploads playlist ID for channel {channel_id}")
        try:
            request = self.youtube.channels().list(
                part="contentDetails",
                id=channel_id
            )
            response = request.execute()
            if response and 'items' in response and response['items']:
                content_details = response['items'][0].get('contentDetails', {})
                related_playlists = content_details.get('relatedPlaylists', {})
                uploads_id = related_playlists.get('uploads')
                if uploads_id:
                    logger.debug(f"Found uploads playlist ID: {uploads_id} for channel {channel_id}")
                    return uploads_id
                else:
                    logger.warning(f"'uploads' playlist ID not found in relatedPlaylists for channel {channel_id}")
                    return None
            else:
                 logger.warning(f"No items found in channel list response for {channel_id}")
                 return None
        except HttpError as e:
            error_details = {}
            try:
                error_content = getattr(e, 'content', b'{}')
                error_details = json.loads(error_content.decode('utf-8')).get('error', {}).get('errors', [{}])[0]
            except Exception: pass
            reason = error_details.get('reason', 'unknown')
            message = error_details.get('message', str(e))
            logger.error(f"API error fetching uploads playlist for channel {channel_id}: {e.resp.status} Reason: {reason} Msg: {message}")
            if e.resp.status == 404: # Channel not found
                 logger.warning(f"YouTube channel {channel_id} not found.")
        except Exception as e:
            logger.error(f"Unexpected error fetching uploads playlist for {channel_id}: {e}", exc_info=True)
        return None

    def get_video_details(self, video_id: str) -> Optional[Dict[str, Any]]:
        """Fetches additional details like duration, potentially updated snippet for a video."""
        if not self.youtube:
             logger.error("YouTube client not initialized, cannot get video details.")
             return None
        logger.debug(f"Fetching details for video {video_id}")
        try:
            request = self.youtube.videos().list(
                part="contentDetails,snippet", # Fetch snippet too for redundancy/completeness
                id=video_id
            )
            response = request.execute()
            if response and 'items' in response and response['items']:
                item = response['items'][0]
                details = item.get('contentDetails', {})
                snippet = item.get('snippet', {})

                # Parse Duration
                duration_iso = details.get('duration')
                duration_seconds = None
                if duration_iso:
                    try:
                        duration_seconds = int(isodate.parse_duration(duration_iso).total_seconds())
                    except (isodate.ISO8601Error, ValueError, TypeError) as dur_err:
                        logger.warning(f"Could not parse duration '{duration_iso}' for video {video_id}: {dur_err}")

                return {
                    'duration_seconds': duration_seconds,
                    'title': snippet.get('title'),
                    'description': snippet.get('description'),
                    'channel_title': snippet.get('channelTitle'),
                    'tags': snippet.get('tags', []) # Include video tags if available
                }
            else:
                 logger.warning(f"No items found in video details response for {video_id}")
                 return None
        except HttpError as e:
            error_details = {}
            try:
                error_content = getattr(e, 'content', b'{}')
                error_details = json.loads(error_content.decode('utf-8')).get('error', {}).get('errors', [{}])[0]
            except Exception: pass
            reason = error_details.get('reason', 'unknown')
            message = error_details.get('message', str(e))
            logger.error(f"API error fetching details for video {video_id}: {e.resp.status} Reason: {reason} Msg: {message}")
            if e.resp.status == 404: # Video not found or private
                 logger.warning(f"YouTube video {video_id} not found or access denied.")
        except Exception as e:
             logger.error(f"Unexpected error fetching video details for {video_id}: {e}", exc_info=True)
        return None

    def check_channel(self, candidate_id: str, channel_identifier: str, listener_state: Optional[Dict]):
        """
        Checks a specific YouTube channel for new videos since the last check time
        stored in listener_state (fetched from MCP).
        """
        if not self.youtube:
            logger.error(f"YouTube client not available, cannot check channel {channel_identifier} for candidate {candidate_id}")
            return

        channel_id = channel_identifier # Assume identifier IS the channel ID for YouTube
        start_time = time.time()
        # Ensure listener_state is a dict, even if empty
        listener_state = listener_state or {}
        logger.info(f"Checking YouTube channel {channel_id} for Cand:{candidate_id} / State:{listener_state}")

        # Fetch the special 'uploads' playlist ID for the channel
        uploads_playlist_id = self.get_channel_uploads_playlist_id(channel_id)
        if not uploads_playlist_id:
            logger.warning(f"Could not find uploads playlist ID for channel {channel_id}. Skipping check.")
            # Don't update state on failure to find playlist
            return

        # Determine the timestamp to search after from the state provided by ListenerManager
        last_checked_iso = listener_state.get('last_checked_timestamp')
        published_after_dt_check = None
        if last_checked_iso:
             try:
                 # Use the exact last checked time for comparison
                 published_after_dt_check = datetime.fromisoformat(last_checked_iso.replace('Z', '+00:00')).astimezone(timezone.utc)
                 logger.info(f"Checking for videos published strictly after: {published_after_dt_check.isoformat()}")
             except ValueError:
                  logger.error(f"Invalid timestamp format retrieved from state for channel {channel_id}: {last_checked_iso}. Checking all recent videos.")
                  last_checked_iso = None # Treat as if no previous state

        new_videos_processed_count = 0
        next_page_token = None
        # Track the actual latest publish time encountered in *this run* for state update
        # Initialize with the previous state's time if available
        latest_publish_time_this_run = published_after_dt_check
        max_pages_to_check = 5 # Limit pages per run to manage quota/time
        processed_video_ids_this_run = set() # Avoid duplicate processing in same run
        api_error_occurred = False
        ingestion_error_occurred = False

        try:
            for page_num in range(max_pages_to_check):
                logger.debug(f"Fetching playlist page {page_num + 1}/{max_pages_to_check} for channel {channel_id}...")
                try:
                    request = self.youtube.playlistItems().list(
                        part="snippet,contentDetails",
                        playlistId=uploads_playlist_id,
                        maxResults=50,
                        pageToken=next_page_token
                    )
                    response = request.execute()
                except HttpError as e:
                     # Handle API error for this specific page request
                     error_details = {}
                     try:
                         error_content = getattr(e, 'content', b'{}')
                         error_details = json.loads(error_content.decode('utf-8')).get('error', {}).get('errors', [{}])[0]
                     except Exception: pass
                     reason = error_details.get('reason', 'unknown')
                     message = error_details.get('message', str(e))
                     logger.error(f"YouTube API error on page {page_num + 1} for channel {channel_id}: {e.resp.status} Reason: {reason} Msg: {message}", exc_info=False)
                     if e.resp.status == 403 and reason in ['quotaExceeded', 'dailyLimitExceeded']:
                          logger.critical(f"YOUTUBE API QUOTA EXCEEDED during pagination for channel {channel_id}.")
                          api_error_occurred = True # Mark error occurred
                     # Stop processing this channel on API error
                     break # Break outer page loop
                except Exception as e:
                     logger.error(f"Unexpected error fetching playlist page {page_num + 1} for channel {channel_id}: {e}", exc_info=True)
                     api_error_occurred = True
                     break # Break outer page loop


                items = response.get('items', [])
                logger.debug(f"Received {len(items)} items on page {page_num + 1}.")

                if not items:
                     logger.debug(f"No more items found for channel {channel_id}.")
                     break # Exit outer loop if no items returned

                stop_processing_page = False
                for item in items:
                    snippet = item.get('snippet', {})
                    content_details = item.get('contentDetails', {})
                    video_id = content_details.get('videoId')
                    publish_time_str = content_details.get('videoPublishedAt')

                    if not video_id or not publish_time_str:
                         logger.warning(f"Skipping item due to missing videoId or publishedAt: {item.get('id')}")
                         continue

                    if video_id in processed_video_ids_this_run:
                         continue # Skip duplicate already processed in this run

                    try:
                        publish_time_dt = datetime.fromisoformat(publish_time_str.replace('Z', '+00:00')).astimezone(timezone.utc)
                    except ValueError:
                         logger.warning(f"Could not parse publish time '{publish_time_str}' for video {video_id}. Skipping.")
                         continue

                    # Update the latest publish time seen in this batch
                    if latest_publish_time_this_run is None:
                         latest_publish_time_this_run = publish_time_dt
                    else:
                         latest_publish_time_this_run = max(latest_publish_time_this_run, publish_time_dt)

                    # Check if the video is actually new compared to the last state
                    if published_after_dt_check and publish_time_dt <= published_after_dt_check:
                        # Reached videos already seen based on timestamp. Stop.
                        logger.info(f"Reached videos at/before last check time ({publish_time_str} <= {last_checked_iso}). Stopping check for channel {channel_id}.")
                        stop_processing_page = True
                        break # Break inner item loop

                    # --- Process the New Video ---
                    logger.info(f"Processing NEW video: ID={video_id}, Published={publish_time_str}, Channel={channel_id}")
                    processed_video_ids_this_run.add(video_id)

                    video_details = self.get_video_details(video_id) or {} # Returns dict or {}
                    transcript = _get_youtube_transcript(video_id) # Returns None currently
                    main_content = transcript if transcript else f"Title: {video_details.get('title', snippet.get('title', ''))}\nDescription: {video_details.get('description', snippet.get('description', ''))}"

                    post_data = {
                        "candidate_id": candidate_id,
                        "source_platform": "YouTube",
                        "post_id": video_id,
                        "content": main_content.strip(),
                        "timestamp": publish_time_dt, # Keep as datetime for now
                        "url": f"https://www.youtube.com/channel/UCid{video_id}", # Standard YT URL
                        "author_username": video_details.get('channel_title', snippet.get('videoOwnerChannelTitle', channel_id)),
                        "raw_data": {"playlistItem": item, "videoDetails": video_details},
                        "video_title": video_details.get('title', snippet.get('title')),
                        "video_description": video_details.get('description', snippet.get('description')),
                        "video_duration_seconds": video_details.get('duration_seconds'),
                        "video_tags": video_details.get('tags', [])
                    }

                    if self._send_to_ingestion(post_data):
                         new_videos_processed_count += 1
                    else:
                         ingestion_error_occurred = True
                         logger.error(f"Stopping further processing for channel {channel_id} due to ingestion error for video {video_id}.")
                         stop_processing_page = True
                         break # Break inner item loop

                # Check if inner loop was stopped
                if stop_processing_page:
                    break # Break outer page loop

                # Prepare for next page
                next_page_token = response.get('nextPageToken')
                if not next_page_token:
                    logger.debug(f"No more pages for channel {channel_id}.")
                    break # Exit outer loop if no next page token

            # --- End of Page Loop ---

        except Exception as e:
            # Catch unexpected errors during the main loop logic
            logger.error(f"An unexpected error occurred during loop for channel {channel_id}: {e}", exc_info=True)
            api_error_occurred = True # Treat as critical error for state update

        # --- Update Listener State ---
        # Update state via MCP *only if* the check completed without critical API errors AND no ingestion errors occurred.
        # Use the latest publish time encountered during the run.
        if not api_error_occurred and not ingestion_error_occurred:
            if latest_publish_time_this_run:
                 # Format timestamp consistently (UTC 'Z') for storage state
                 new_timestamp_iso = latest_publish_time_this_run.astimezone(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')
                 should_update_state = True
                 # Only update if the new timestamp is actually newer than the last known state
                 if last_checked_iso:
                      try:
                          last_dt = datetime.fromisoformat(last_checked_iso.replace('Z', '+00:00')).astimezone(timezone.utc)
                          if latest_publish_time_this_run <= last_dt:
                               should_update_state = False
                               logger.debug(f"Latest publish time found ({new_timestamp_iso}) is not newer than last state ({last_checked_iso}). Not updating state.")
                      except ValueError: pass # If last state invalid, update anyway

                 if should_update_state:
                     logger.info(f"Updating last checked timestamp via MCP for Cand:{candidate_id} (YouTube) to {new_timestamp_iso}")
                     update_success = self._update_listener_state_mcp(candidate_id, 'youtube', {'last_checked_timestamp': new_timestamp_iso})
                     if not update_success:
                          logger.error(f"FAILED to update listener state via MCP for Cand:{candidate_id}, Platform:youtube after successful check.")

            elif not last_checked_iso and new_videos_processed_count == 0:
                 # First successful run, no videos found, set timestamp to now
                 now_iso = datetime.now(timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')
                 logger.info(f"First successful run for channel {channel_id} found no videos. Setting timestamp via MCP to {now_iso}")
                 self._update_listener_state_mcp(candidate_id, 'youtube', {'last_checked_timestamp': now_iso})
            else:
                 logger.info(f"No new videos processed or no newer timestamp found for channel {channel_id}. State not updated.")
        else:
             logger.warning(f"Skipping listener state update for channel {channel_id} due to API or Ingestion errors during check.")


        duration = time.time() - start_time
        logger.info(f"Finished checking YouTube channel {channel_id}. Processed {new_videos_processed_count} new videos in {duration:.2f}s.")

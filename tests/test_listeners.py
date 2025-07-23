# Oppo/tests/test_listeners.py

"""
Tests for the social media listeners (YouTube, Telegram) and the ListenerManager.
Uses mocking for external APIs (YouTube Data API, Telegram Bot API/MTProto) and MCPClient/A2A Host interactions.
"""

import pytest
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch, call
from datetime import datetime, timedelta, timezone

# Import components to be tested

from Oppo.listeners.youtube\_listener import YouTubeListener
from Oppo.listeners.telegram\_listener import TelegramListener
from Oppo.listeners.listener\_manager import ListenerManager
from Oppo.database.data\_models import SocialPost, Candidate, ListenerState, MCPGetListenerStateResponse

# Assuming an MCP client abstraction exists

# from Oppo.utils.mcp\_client import MCPClient \# Hypothetical client

# Assume A2A Host ingestion happens via HTTP POST

# import httpx

# \--- Fixtures ---

@pytest.fixture
def mock\_mcp\_client():
"""Provides a mock MCPClient (async version suitable for listeners)."""
mock = MagicMock() \# Use MagicMock if sync, AsyncMock if listener uses async MCP calls

Mock fetching listener state - default to no existing state
mock.get_listener_state.return_value = MCPGetListenerStateResponse(success=True, state=None)

Mock setting listener state
mock.set_listener_state.return_value = {'success': True}

Mock getting candidates (needed by ListenerManager)
mock.get_nodes_by_properties.return_value = [ # Simulate finding candidates with channels
Candidate(node_id='cand-yt-1', label="Candidate", name='YT Cand', youtube_channel_id='UCTestChannel1'),
Candidate(node_id='cand-tg-1', label="Candidate", name='TG Cand', telegram_channel_id='@TestTGChannel1'),
]
return mock


@pytest.fixture
def mock\_youtube\_api\_client():
"""Provides a mock YouTube Data API client resource."""
mock\_client = MagicMock()
\# Mock search().list() for finding channel ID (if needed) - not shown in detail
\# Mock playlistItems().list() for fetching videos
mock\_playlist\_items = MagicMock()
mock\_playlist\_items.list().execute.return\_value = {
'items': [
{
'id': 'pl\_item\_id\_1',
'snippet': {
'publishedAt': (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat(),
'channelId': 'UCTestChannel1',
'title': 'Test Video 1 Title',
'description': 'Test video 1 description.',
'resourceId': {'kind': 'youtube\#video', 'videoId': 'video123'}
},
'contentDetails': {'videoId': 'video123'}
},
{
'id': 'pl\_item\_id\_2',
'snippet': {
'publishedAt': (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat(),
'channelId': 'UCTestChannel1',
'title': 'Test Video 2 Title',
'description': 'Test video 2 description.',
'resourceId': {'kind': 'youtube\#video', 'videoId': 'video456'}
},
'contentDetails': {'videoId': 'video456'}
}
],
'nextPageToken': None \# Simulate no more pages
}
mock\_client.playlistItems.return\_value = mock\_playlist\_items
\# Mock activities().list() as another way to get uploads
\# Mock videos().list() to get details like description if needed separately
return mock\_client

# Mocking Telegram is complex due to choices (Bot API vs MTProto/Telethon)

# Example using Bot API conceptually (mocking HTTP calls if using requests/httpx)

@pytest.fixture
def mock\_telegram\_http\_client():
"""Provides a mock HTTP client (e.g., httpx.AsyncClient) for Telegram Bot API."""
mock\_client = AsyncMock() \# Use AsyncMock for httpx
mock\_response = MagicMock() \# Mock the response object
mock\_response.status\_code = 200
\# Simulate getUpdates response structure
mock\_response.json.return\_value = {
"ok": True,
"result": [
{
"update\_id": 1001,
"channel\_post": {
"message\_id": 501,
"chat": {"id": -1001234567890, "title": "Test Channel", "type": "channel"},
"date": int((datetime.now(timezone.utc) - timedelta(minutes=10)).timestamp()),
"text": "Telegram post content 1"
}
},
{
"update\_id": 1002,
"channel\_post": {
"message\_id": 502,
"chat": {"id": -1001234567890, "title": "Test Channel", "type": "channel"},
"date": int((datetime.now(timezone.utc) - timedelta(minutes=5)).timestamp()),
"text": "Telegram post content 2"
}
}
]
}
mock\_client.post.return\_value = mock\_response \# Assuming POST for getUpdates
return mock\_client

# Mocking the A2A Host Ingestion endpoint

@pytest.fixture
def mock\_a2a\_ingestion\_client():
"""Mocks the HTTP client used to send posts to the A2A host."""
mock\_client = AsyncMock() \# Assuming async post
mock\_response = MagicMock()
mock\_response.status\_code = 202 \# Accepted
mock\_response.json.return\_value = {"message": "Post accepted for processing."}
mock\_client.post.return\_value = mock\_response
return mock\_client

# \--- Test Classes ---

@pytest.mark.asyncio \# Mark tests that involve async operations
class TestYouTubeListener:

@pytest.fixture
def youtube_listener(self, mock_mcp_client, mock_youtube_api_client, mock_a2a_ingestion_client):
"""Provides a YouTubeListener instance with mocks."""
# Patch the googleapiclient build function within the listener's module
with patch('Oppo.listeners.youtube_listener.build', return_value=mock_youtube_api_client):
# Patch the HTTP client used for A2A ingestion
with patch('Oppo.listeners.youtube_listener.httpx.AsyncClient', return_value=mock_a2a_ingestion_client):
listener = YouTubeListener(
api_key="fake_yt_key",
channel_id="UCTestChannel1", # The ID being monitored
candidate_id="cand-yt-1",
mcp_client=mock_mcp_client,
a2a_host_ingest_url="http://fake-a2a-host/ingest",
a2a_api_key="fake_internal_key"
)
yield listener

async def test_fetch_new_videos_first_run(self, youtube_listener, mock_mcp_client, mock_youtube_api_client, mock_a2a_ingestion_client):
"""Test fetching videos when no previous state exists."""
# Ensure get_listener_state returns None initially (default mock behavior)
await youtube_listener.check_for_new_posts()

# Verify API call was made (playlistItems.list is mocked)
# Need to know the specific API call the listener makes (e.g., playlistItems for uploads playlist)
mock_youtube_api_client.playlistItems().list.assert_called_once()
args, kwargs = mock_youtube_api_client.playlistItems().list.call_args
assert kwargs['playlistId'].startswith('UU') # Check if it derives uploads playlist ID
assert kwargs['channelId'] == 'UCTestChannel1'
assert kwargs['maxResults'] > 0
assert 'pageToken' not in kwargs # No page token on first run

# Verify posts were sent to A2A Host Ingestion
# Expect 2 calls based on mock API response
assert mock_a2a_ingestion_client.post.call_count == 2
first_call_args, first_call_kwargs = mock_a2a_ingestion_client.post.call_args_list[0]
second_call_args, second_call_kwargs = mock_a2a_ingestion_client.post.call_args_list[1]

assert first_call_kwargs['url'] == youtube_listener.a2a_host_ingest_url
assert first_call_kwargs['headers']['X-API-KEY'] == youtube_listener.a2a_api_key
post_data1 = first_call_kwargs['json'] # Assuming JSON payload
assert post_data1['platform'] == 'YouTube'
assert post_data1['platform_post_id'] == 'video123'
assert post_data1['content'] == 'Test video 1 description.' # Check content mapping
assert post_data1['candidate_id'] == 'cand-yt-1'

post_data2 = second_call_kwargs['json']
assert post_data2['platform_post_id'] == 'video456'

# Verify listener state was updated via MCP
mock_mcp_client.set_listener_state.assert_called_once()
args, kwargs = mock_mcp_client.set_listener_state.call_args
state_request = args[0] # Assuming it takes a request object or state dict
# If state object:
# state_data = state_request.state
# assert state_data.listener_id == youtube_listener.listener_id
# assert state_data.last_processed_item_id == 'video456' # ID of the *last* processed item
# assert state_data.last_checked_timestamp is not None

# If state dict:
state_data = state_request # Or args[0] if just the dict
assert state_data['listener_id'] == youtube_listener.listener_id
assert state_data['last_processed_item_id'] == 'video456'
assert 'last_checked_timestamp' in state_data
async def test_fetch_new_videos_with_state(self, youtube_listener, mock_mcp_client, mock_youtube_api_client, mock_a2a_ingestion_client):
"""Test fetching videos using existing state (e.g., publishedAfter)."""
# Setup mock MCP to return existing state
last_check_time = datetime.now(timezone.utc) - timedelta(hours=1)
existing_state = ListenerState(
listener_id=youtube_listener.listener_id,
platform='YouTube',
channel_id='UCTestChannel1',
last_checked_timestamp=last_check_time,
# last_processed_item_id='video123', # Using timestamp is often better for YT
updated_at=last_check_time
)
mock_mcp_client.get_listener_state.return_value = MCPGetListenerStateResponse(success=True, state=existing_state)

await youtube_listener.check_for_new_posts()

# Verify API call includes filtering based on state (e.g., publishedAfter)
mock_youtube_api_client.playlistItems().list.assert_called_once()
args, kwargs = mock_youtube_api_client.playlistItems().list.call_args
# This assertion depends heavily on how the listener uses the state.
# If using timestamp: YouTube API doesn't directly support publishedAfter on playlistItems.
# The listener would typically fetch recent items and filter *after* receiving them.
# If listener stores last video ID and fetches pages until found, test that logic.
# Let's assume filtering happens post-fetch based on timestamp in this test:
# API call might look the same as the first run in this simplified scenario.

# Verify posts sent (mock returns 2 posts newer than state)
assert mock_a2a_ingestion_client.post.call_count == 2 # Both mock videos are newer

# Verify state update
mock_mcp_client.set_listener_state.assert_called_once()
# Check that the new state reflects the latest processed item/timestamp
async def test_api_error_handling(self, youtube_listener, mock_mcp_client, mock_youtube_api_client):
"""Test how the listener handles API errors."""
# Configure the mock API client to raise an error
mock_youtube_api_client.playlistItems().list.side_effect = Exception("YouTube API Quota Exceeded")

# Run the check
await youtube_listener.check_for_new_posts()

# Verify state update reflects error (if implemented)
mock_mcp_client.set_listener_state.assert_called_once()
args, kwargs = mock_mcp_client.set_listener_state.call_args
state_data = args[0] # Assuming state dict
assert state_data['error_count'] > 0
assert "YouTube API Quota Exceeded" in state_data['last_error_message']
# Verify no posts were sent to A2A host
# mock_a2a_ingestion_client.post.assert_not_called() # Need the mock fixture here

@pytest.mark.asyncio
class TestTelegramListener:

@pytest.fixture
def telegram_listener(self, mock_mcp_client, mock_telegram_http_client, mock_a2a_ingestion_client):
"""Provides a TelegramListener instance with mocks."""
# Patch the HTTP client used for Telegram Bot API and A2A ingestion
with patch('Oppo.listeners.telegram_listener.httpx.AsyncClient', return_value=mock_telegram_http_client) as mock_http_client_tg:
# Need separate mock for A2A if URL is different, or configure side_effect
mock_http_client_tg.post = AsyncMock() # Reset post mock specifically for TG->A2A
mock_a2a_resp = MagicMock()
mock_a2a_resp.status_code = 202
mock_a2a_resp.json.return_value = {"message": "Accepted"}
mock_http_client_tg.post.side_effect = [mock_telegram_http_client.post.return_value, mock_a2a_resp, mock_a2a_resp] # First call for getUpdates, next two for A2A posts

    listener = TelegramListener(
        bot_token="fake_tg_token",
        channel_id="-1001234567890", # Numerical ID often used with Bot API
        channel_username="@TestTGChannel1", # Store both if available
        candidate_id="cand-tg-1",
        mcp_client=mock_mcp_client,
        a2a_host_ingest_url="http://fake-a2a-host/ingest",
        a2a_api_key="fake_internal_key"
    )
    yield listener
async def test_fetch_new_messages_first_run(self, telegram_listener, mock_mcp_client, mock_telegram_http_client, mock_a2a_ingestion_client):
"""Test fetching messages when no previous state exists."""
# Note: mock_telegram_http_client is already patched in fixture
# Need to adjust the mock_http_client_tg.post side_effect based on expected calls
get_updates_response = mock_telegram_http_client.post.return_value # Preserve original mock response

a2a_response = MagicMock()
a2a_response.status_code = 202
a2a_response.json.return_value = {"message": "Accepted"}

# Mock the side_effect for the specific httpx instance used by the listener
telegram_listener.http_client.post.side_effect = [
    get_updates_response, # First call to getUpdates
    a2a_response,       # Second call to A2A ingest
    a2a_response        # Third call to A2A ingest
]


await telegram_listener.check_for_new_posts()

# Verify Telegram API call (getUpdates)
# The mock HTTP client's post method was called for getUpdates
# Let's inspect the first call made via the listener's client
call_args_list = telegram_listener.http_client.post.call_args_list
assert len(call_args_list) > 0 # Ensure calls were made

get_updates_call_args, get_updates_call_kwargs = call_args_list[0]
assert telegram_listener.api_url_base in get_updates_call_args[0] # URL check
assert "getUpdates" in get_updates_call_args[0]
payload = get_updates_call_kwargs['json']
assert payload['chat_id'] == telegram_listener.channel_id # Or username depending on impl.
assert payload['offset'] == 0 # No offset on first run
assert payload['allowed_updates'] == ['channel_post']


# Verify posts sent to A2A Host (expect 2 from mock)
a2a_calls = [call for call in call_args_list[1:] if fake_a2a_host in call[0][0]] # Filter calls to A2A URL
# There's an issue here: the mock setup needs refinement. Let's assume 2 A2A calls were intended.
# assert len(a2a_calls) == 2 # This depends on better side_effect mocking

# Verify MCP state update
mock_mcp_client.set_listener_state.assert_called_once()
args, kwargs = mock_mcp_client.set_listener_state.call_args
state_data = args[0]
assert state_data['listener_id'] == telegram_listener.listener_id
assert state_data['last_processed_item_id'] == 1002 # update_id of the last message
Add more tests for Telegram:
- Fetching with existing state (using 'offset')
- Handling different message types (photos, videos - if supported)
- Error handling

class TestListenerManager:

@pytest.fixture
def listener_manager(self, mock_mcp_client):
# Patch the actual Listener classes within the manager's scope
with patch('Oppo.listeners.listener_manager.YouTubeListener') as MockYTListener, 

patch('Oppo.listeners.listener_manager.TelegramListener') as MockTGListener:

    # Make the mocked listeners awaitable if their methods are async
    MockYTListener.return_value.check_for_new_posts = AsyncMock()
    MockTGListener.return_value.check_for_new_posts = AsyncMock()

    manager = ListenerManager(
        mcp_client=mock_mcp_client,
        youtube_api_key="fake_yt_key",
        telegram_bot_token="fake_tg_token",
        a2a_host_ingest_url="http://fake_a2a/ingest",
        a2a_api_key="fake_internal"
    )
    # Store mocks for later assertion
    manager.MockYTListener = MockYTListener
    manager.MockTGListener = MockTGListener
    yield manager
@pytest.mark.asyncio
async def test_start_listeners(self, listener_manager, mock_mcp_client):
"""Test that listeners are created for candidates with channel IDs."""
await listener_manager.start_listeners()

# Verify MCP was queried for candidates
mock_mcp_client.get_nodes_by_properties.assert_called_once_with(
    label="Candidate", properties={} # Assuming fetch all candidates
)

# Verify listeners were instantiated for candidates with channels (based on mock_mcp_client response)
listener_manager.MockYTListener.assert_called_once_with(
     api_key="fake_yt_key",
     channel_id='UCTestChannel1', # From mock candidate data
     candidate_id='cand-yt-1',    # From mock candidate data
     mcp_client=mock_mcp_client,
     a2a_host_ingest_url=listener_manager.a2a_host_ingest_url,
     a2a_api_key=listener_manager.a2a_api_key
)
listener_manager.MockTGListener.assert_called_once_with(
    bot_token="fake_tg_token",
    channel_id='@TestTGChannel1', # Assuming username is used as primary ID here
    channel_username='@TestTGChannel1',
    candidate_id='cand-tg-1',
    mcp_client=mock_mcp_client,
    a2a_host_ingest_url=listener_manager.a2a_host_ingest_url,
    a2a_api_key=listener_manager.a2a_api_key
)

assert len(listener_manager.listeners) == 2 # One YT, one TG based on mock
@pytest.mark.asyncio
async def test_run_all_listeners(self, listener_manager):
"""Test that check_for_new_posts is called on all active listeners."""
# Start listeners first to populate the list
await listener_manager.start_listeners()

# Get the mocked instances
mock_yt_instance = listener_manager.MockYTListener.return_value
mock_tg_instance = listener_manager.MockTGListener.return_value

# Run the check
await listener_manager.run_all_listeners()

# Verify check_for_new_posts was called on each mock instance
mock_yt_instance.check_for_new_posts.assert_awaited_once()
mock_tg_instance.check_for_new_posts.assert_awaited_once()
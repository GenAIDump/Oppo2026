# Oppo/tests/test_data_collection.py

"""
Tests for the data collection components (crawlers, processors).
Uses mocking for HTTP requests (requests/httpx) and MCPClient interactions.
"""

import pytest
import requests \# Use requests for mocking sync crawlers

# import httpx \# Use httpx for mocking async crawlers/processors

from unittest.mock import MagicMock, patch, call
from datetime import datetime

# Import components to be tested

from Oppo.data\_collection.crawlers.fec\_crawler import FECCrawler \# Example crawler
from Oppo.data\_collection.processors.fec\_processor import FECProcessor \# Example processor
from Oppo.database.data\_models import Candidate \# Example data model

# Assuming an MCP client abstraction exists

# from Oppo.utils.mcp\_client import MCPClient \# Hypothetical client

# \--- Fixtures ---

@pytest.fixture
def mock\_requests\_session():
"""Provides a mock requests.Session."""
mock\_session = MagicMock(spec=requests.Session)
mock\_response = MagicMock(spec=requests.Response)
mock\_response.status\_code = 200
mock\_response.json.return\_value = {"results": [{"candidate\_id": "H0PA01123", "name": "Mock Candidate"}]} \# Example FEC API structure
mock\_response.text = '{"results": [{"candidate\_id": "H0PA01123", "name": "Mock Candidate"}]}'
mock\_response.raise\_for\_status.return\_value = None \# Simulate successful response
mock\_session.get.return\_value = mock\_response
return mock\_session

@pytest.fixture
def mock\_mcp\_client():
"""Provides a mock MCPClient."""
mock = MagicMock() \# Use MagicMock for sync methods
\# Mock storing node data
mock.store\_node.return\_value = {'success': True, 'node\_id': 'cand-mcp-123'}
return mock

@pytest.fixture
def fec\_crawler(mock\_requests\_session):
"""Provides an FECCrawler instance with a mocked session."""
\# Patch 'requests.Session' within the crawler's module scope
with patch('Oppo.data\_collection.crawlers.fec\_crawler.requests.Session', return\_value=mock\_requests\_session):
crawler = FECCrawler(api\_key="fake\_fec\_key")
\# If crawler creates session internally, patching might be different
\# crawler.session = mock\_requests\_session \# Alternative: Directly inject mock
yield crawler \# Use yield if setup/teardown needed

@pytest.fixture
def fec\_processor(mock\_mcp\_client):
"""Provides an FECProcessor instance with a mocked MCP client."""
processor = FECProcessor(mcp\_client=mock\_mcp\_client)
return processor

# \--- Test Classes ---

class TestFECCrawler:
def test\_initialization(self):
\# Test basic init without mocks if session isn't created immediately
crawler = FECCrawler(api\_key="test\_key")
assert crawler.api\_key == "test\_key"
assert "api.open.fec.gov" in crawler.base\_url

def test_fetch_candidates(self, fec_crawler, mock_requests_session):
"""Test fetching candidate data successfully."""
candidates_data = fec_crawler.fetch_candidates(year=2024, state='PA')

# Verify the correct API endpoint was called
mock_requests_session.get.assert_called_once()
args, kwargs = mock_requests_session.get.call_args
url = args[0]
params = kwargs.get('params', {})
assert fec_crawler.base_url in url
assert "/candidates" in url
assert params.get('election_year') == [2024] # FEC API often expects list params
assert params.get('state') == 'PA'
assert params.get('api_key') == "fake_fec_key"

# Verify the returned data matches the mocked response
assert candidates_data == [{"candidate_id": "H0PA01123", "name": "Mock Candidate"}] # Based on mock_response
def test_fetch_candidates_api_error(self, fec_crawler, mock_requests_session):
"""Test handling of API errors (e.g., 404, 500)."""
# Configure the mock response for an error
mock_response = MagicMock(spec=requests.Response)
mock_response.status_code = 404
mock_response.raise_for_status.side_effect = requests.exceptions.HTTPError("Not Found")
mock_requests_session.get.return_value = mock_response

# Expect the crawler method to handle the error gracefully (e.g., return None or empty list, log error)
# Depending on implementation, it might raise the error or catch it.
# Let's assume it catches and returns empty list
result = fec_crawler.fetch_candidates(year=2024, state='ZZ') # Invalid state to trigger error?
assert result == [] # Or None, depending on error handling

# Or test if it raises the exception
# with pytest.raises(requests.exceptions.HTTPError):
#     fec_crawler.fetch_candidates(year=2024, state='ZZ')

class TestFECProcessor:
def test\_initialization(self, mock\_mcp\_client):
processor = FECProcessor(mcp\_client=mock\_mcp\_client)
assert processor.mcp\_client == mock\_mcp\_client

def test_process_candidate_data(self, fec_processor, mock_mcp_client):
"""Test processing valid candidate data and storing via MCP."""
raw_data = [{"candidate_id": "H0PA01123", "name": "Mock Candidate", "party_full": "REPUBLICAN", "state":"PA", "district": "01"}]   

processed_count = fec_processor.process_candidates(raw_data)

assert processed_count == 1

# Verify that MCP client's store_node was called
mock_mcp_client.store_node.assert_called_once()
args, kwargs = mock_mcp_client.store_node.call_args
mcp_request = args[0] # Assuming store_node takes a request object or dict

# If store_node takes keyword args directly:
# assert kwargs['node_label'] == Candidate.label
# properties = kwargs['properties']
# assert properties['fec_id'] == "H0PA01123"
# assert properties['name'] == "Mock Candidate"
# assert properties['party'] == "Republican" # Check transformations
# assert properties['state'] == "PA"
# assert properties['district'] == "01"
# assert kwargs['unique_field'] == 'fec_id'

# If store_node takes a request object:
assert mcp_request.node_label == "Candidate" # Access attributes if it's an object
properties = mcp_request.properties
assert properties['fec_id'] == "H0PA01123"
assert properties['name'] == "Mock Candidate"
assert properties['party'] == "Republican" # Check transformations
assert properties['state'] == "PA"
assert properties['district'] == "01"
assert mcp_request.unique_field == 'fec_id'
def test_process_invalid_data(self, fec_processor, mock_mcp_client):
"""Test handling of incomplete or invalid data."""
# Missing required fields like 'candidate_id' or 'name'
raw_data = [{"name": "Incomplete Candidate"}]
processed_count = fec_processor.process_candidates(raw_data)

assert processed_count == 0 # Should skip invalid records
mock_mcp_client.store_node.assert_not_called() # MCP should not be called
def test_mcp_storage_failure(self, fec_processor, mock_mcp_client):
"""Test handling when MCP fails to store the node."""
# Configure MCP mock to simulate failure
mock_mcp_client.store_node.return_value = {'success': False, 'error': 'Database connection failed'}

raw_data = [{"candidate_id": "H0PA01123", "name": "Mock Candidate", "party_full": "REPUBLICAN", "state":"PA", "district": "01"}]
processed_count = fec_processor.process_candidates(raw_data)

# Processor might still count attempt, or return 0 based on success. Adjust assertion accordingly.
# Let's assume it counts the attempt but logs the error.
assert processed_count == 0 # Or 1 depending on logic, but storage failed.
mock_mcp_client.store_node.assert_called_once() # Called once, but failed.

# Add similar Test classes for other crawlers (Congress, Ballotpedia, etc.) and processors

# Remember to mock their specific API responses and expected processed data structures.

# Example for a different crawler (simplified)

# class TestCongressCrawler:

# @patch('Oppo.data\_collection.crawlers.congress\_crawler.requests.get')

# def test\_fetch\_member\_details(self, mock\_get):

# mock\_response = MagicMock()

# mock\_response.status\_code = 200

# \# Mock the HTML content or JSON response from Congress.gov

# mock\_response.text = "<html><body><h1>Mock Member</h1></body></html>"

# mock\_get.return\_value = mock\_response

# crawler = CongressCrawler()

# details = crawler.fetch\_member\_details(member\_id="MOCK123")

# mock\_get.assert\_called\_once\_with("https://www.congress.gov/member/MOCK123")

# assert details is not None \# Or check parsed content
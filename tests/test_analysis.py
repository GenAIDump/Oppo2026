# Oppo/tests/test_analysis.py

"""
Tests for the analysis components (LLM analyzers, decision engine).
Uses extensive mocking for LLMInterface and MCPClient interactions.
"""

import pytest
import uuid
from unittest.mock import MagicMock, AsyncMock, patch, call
from datetime import datetime

# Import components to be tested

from Oppo.analysis.llm\_interface import LLMInterface, LLMProvider  \# Assuming enum exists
from Oppo.analysis.contradiction\_detector import ContradictionDetector
from Oppo.analysis.disinformation\_analyzer import DisinformationAnalyzer
from Oppo.analysis.evasion\_detector import EvasionDetector
from Oppo.analysis.fact\_checker import FactChecker
from Oppo.analysis.decision\_engine import DecisionEngine
from Oppo.database.data\_models import SocialPost, Candidate, MCPGetCandidateContextResponse

# Assuming an MCP client abstraction exists for analysis components to use

# If they call MCP HTTP endpoints directly, httpx mocking would be needed instead.

# For simplicity, let's assume an internal client `MCPClient` is used.

# from Oppo.utils.mcp\_client import MCPClient \# Hypothetical client

# \--- Fixtures ---

@pytest.fixture
def mock\_llm\_interface():
"""Provides a mock LLMInterface."""
mock = MagicMock(spec=LLMInterface)
\# Configure mock analyze method to return structured results
mock.analyze.return\_value = {
"score": 0.75,
"explanation": "Mocked LLM explanation.",
"success": True,
"error": None
}
return mock

# If using async calls to MCP

# @pytest.fixture

# def mock\_mcp\_client():

# """Provides a mock MCPClient (async version)."""

# mock = AsyncMock(spec=MCPClient) \# Use AsyncMock for async methods

# \# Mock context fetching

# mock.get\_candidate\_context.return\_value = MCPGetCandidateContextResponse(

# success=True,

# posts=[

# SocialPost(id=str(uuid.uuid4()), platform='Test', platform\_post\_id='ctx1', candidate\_id='cand1', channel\_id='chan1', content='Old post content', published\_at=datetime.utcnow()),

# SocialPost(id=str(uuid.uuid4()), platform='Test', platform\_post\_id='ctx2', candidate\_id='cand1', channel\_id='chan1', content='Another old post', published\_at=datetime.utcnow())

# ]

# )

# \# Mock score updating

# mock.update\_node\_properties.return\_value = {'success': True, 'node\_id': 'post123'} \# Simulate success

# return mock

# If using synchronous calls to MCP

@pytest.fixture
def mock\_mcp\_client():
"""Provides a mock MCPClient (sync version)."""
mock = MagicMock() \# Use MagicMock for sync methods
\# Mock context fetching
mock.get\_candidate\_context.return\_value = MCPGetCandidateContextResponse(
success=True,
posts=[
SocialPost(node\_id=str(uuid.uuid4()), platform='Test', platform\_post\_id='ctx1', candidate\_id='cand1', channel\_id='chan1', content='Old post content', published\_at=datetime.utcnow(), label="SocialPost"),
SocialPost(node\_id=str(uuid.uuid4()), platform='Test', platform\_post\_id='ctx2', candidate\_id='cand1', channel\_id='chan1', content='Another old post', published\_at=datetime.utcnow(), label="SocialPost")
]
)
\# Mock score updating
mock.update\_node\_properties.return\_value = {'success': True, 'node\_id': 'post123'} \# Simulate success
return mock

@pytest.fixture
def sample\_social\_post():
"""Provides a sample SocialPost object for testing."""
return SocialPost(
node\_id=str(uuid.uuid4()),
label="SocialPost",
platform="TestPlatform",
platform\_post\_id="testpost123",
candidate\_id=str(uuid.uuid4()),
channel\_id="testchannel1",
content="This is the content of the post being analyzed.",
published\_at=datetime.utcnow(),
ingested\_at=datetime.utcnow()
)

@pytest.fixture
def sample\_candidate():
"""Provides a sample Candidate object."""
return Candidate(
node\_id=str(uuid.uuid4()),
label="Candidate",
name="Test Candidate",
party="Test Party"
)

# \--- Test Classes ---

class TestContradictionDetector:
def test\_initialization(self, mock\_llm\_interface, mock\_mcp\_client):
detector = ContradictionDetector(mock\_llm\_interface, mock\_mcp\_client, LLMProvider.GEMINI)
assert detector.llm\_interface == mock\_llm\_interface
assert detector.mcp\_client == mock\_mcp\_client
assert detector.provider == LLMProvider.GEMINI

def test_analyze_contradiction(self, mock_llm_interface, mock_mcp_client, sample_social_post):
detector = ContradictionDetector(mock_llm_interface, mock_mcp_client, LLMProvider.GEMINI)
result = detector.analyze(sample_social_post)

# Verify context was fetched via MCP
mock_mcp_client.get_candidate_context.assert_called_once_with(candidate_id=sample_social_post.candidate_id)

# Verify LLM was called with expected task and data
mock_llm_interface.analyze.assert_called_once()
args, kwargs = mock_llm_interface.analyze.call_args
assert kwargs['task_type'] == "contradiction"
assert sample_social_post.content in kwargs['prompt_data']['current_post_content']
assert "Old post content" in kwargs['prompt_data']['historical_context'] # From mock context
assert kwargs['provider'] == LLMProvider.GEMINI

# Verify result structure
assert result['score'] == 0.75 # From mock LLM response
assert "Mocked LLM explanation" in result['explanation']
assert result['success'] is True

class TestDisinformationAnalyzer:
def test\_analyze\_disinformation(self, mock\_llm\_interface, sample\_social\_post):
\# Disinfo analyzer might not need historical context, simpler mocking
analyzer = DisinformationAnalyzer(mock\_llm\_interface, LLMProvider.GEMINI)
result = analyzer.analyze(sample\_social\_post)

# Verify LLM was called
mock_llm_interface.analyze.assert_called_once()
args, kwargs = mock_llm_interface.analyze.call_args
assert kwargs['task_type'] == "disinformation"
assert sample_social_post.content in kwargs['prompt_data']['post_content']
assert kwargs['provider'] == LLMProvider.GEMINI

# Verify result structure
assert result['score'] == 0.75
assert "Mocked LLM explanation" in result['explanation']
assert result['success'] is True

class TestEvasionDetector:
def test\_analyze\_evasion(self, mock\_llm\_interface, sample\_social\_post):
analyzer = EvasionDetector(mock\_llm\_interface, LLMProvider.GEMINI)
result = analyzer.analyze(sample\_social\_post)

# Verify LLM was called
mock_llm_interface.analyze.assert_called_once()
args, kwargs = mock_llm_interface.analyze.call_args
assert kwargs['task_type'] == "evasion"
assert sample_social_post.content in kwargs['prompt_data']['post_content']
assert kwargs['provider'] == LLMProvider.GEMINI

# Verify result structure
assert result['score'] == 0.75
assert "Mocked LLM explanation" in result['explanation']
assert result['success'] is True

class TestFactChecker:
def test\_analyze\_fact\_check(self, mock\_llm\_interface, sample\_social\_post):
analyzer = FactChecker(mock\_llm\_interface, LLMProvider.GEMINI)
result = analyzer.analyze(sample\_social\_post)

# Verify LLM was called
mock_llm_interface.analyze.assert_called_once()
args, kwargs = mock_llm_interface.analyze.call_args
assert kwargs['task_type'] == "fact_check"
assert sample_social_post.content in kwargs['prompt_data']['post_content']
assert kwargs['provider'] == LLMProvider.GEMINI

# Verify result structure (score might be different for fact-check, adjust mock if needed)
assert result['score'] == 0.75 # Example score
assert "Mocked LLM explanation" in result['explanation']
assert result['success'] is True

class TestDecisionEngine:
def test\_calculate\_scores(self, mock\_mcp\_client, sample\_social\_post):
engine = DecisionEngine(mock\_mcp\_client)

# Simulate results from individual analyzers
analysis_results = {
    "contradiction": {"score": 0.8, "explanation": "Exp C"},
    "disinformation": {"score": 0.3, "explanation": "Exp D"},
    "fact_check": {"score": -1.0, "explanation": "Exp F"}, # Example: Claim is false
    "evasion": {"score": 0.1, "explanation": "Exp E"},
}

final_scores = engine.calculate_scores(sample_social_post, analysis_results)

# Verify score calculation logic (example: simple weighted average or max)
# This depends heavily on the actual implementation of calculate_scores
# Let's assume a simple averaging for significance for this test
expected_significance = (0.8 + 0.3 + (1.0) + 0.1) / 4 # Assuming abs(fact_check) contributes
# Use pytest.approx for float comparison
assert final_scores['overall_significance_score'] == pytest.approx(expected_significance, 0.01)
assert final_scores['contradiction_score'] == 0.8
assert final_scores['disinformation_score'] == 0.3
assert final_scores['fact_check_score'] == -1.0
assert final_scores['evasion_score'] == 0.1
assert final_scores['contradiction_explanation'] == "Exp C"
# ... and other explanations

# Verify that the update call to MCP was made
mock_mcp_client.update_node_properties.assert_called_once_with(
    node_id=sample_social_post.node_id,
    properties=final_scores # Check that the calculated scores are passed
)
def test_missing_analysis_results(self, mock_mcp_client, sample_social_post):
engine = DecisionEngine(mock_mcp_client)
# Simulate results where some analyses failed or weren't run
analysis_results = {
"contradiction": {"score": 0.8, "explanation": "Exp C"},
"disinformation": None, # Simulate failure
"fact_check": {"score": 0.5, "explanation": "Exp F"},
"evasion": {"score": 0.1, "explanation": "Exp E"},
}
final_scores = engine.calculate_scores(sample_social_post, analysis_results)

# Check that scores are None where input was None
assert final_scores['disinformation_score'] is None
assert final_scores['disinformation_explanation'] is None
# Check that other scores are still calculated
assert final_scores['contradiction_score'] == 0.8
assert final_scores['overall_significance_score'] is not None # Should still calculate based on available scores

# Verify update call still happens
mock_mcp_client.update_node_properties.assert_called_once()

# Example test for the main analysis orchestration logic (if it exists outside A2A host)

# This depends heavily on how analysis is triggered (e.g., a separate function/class)

# @patch('Oppo.analysis.main\_analyzer.ContradictionDetector') \# Patch the classes

# @patch('Oppo.analysis.main\_analyzer.DisinformationAnalyzer')

# \# ... patch others

# def test\_full\_analysis\_pipeline(MockContradictionDetector, MockDisinformationAnalyzer, \#...

# mock\_llm\_interface, mock\_mcp\_client, sample\_social\_post):

# \# Mock the return values of the analyze methods of the mocked classes

# MockContradictionDetector.return\_value.analyze.return\_value = {"score": 0.8, "explanation": "C"}

# MockDisinformationAnalyzer.return\_value.analyze.return\_value = {"score": 0.3, "explanation": "D"}

# \# ...

# \# Instantiate the main orchestrator (assuming one exists)

# \# orchestrator = AnalysisOrchestrator(mock\_llm\_interface, mock\_mcp\_client)

# \# result = orchestrator.run\_analysis(sample\_social\_post)

# \# Assertions:

# \# - Check that all analyzers were instantiated correctly

# \# - Check that analyze methods were called on each instance

# \# - Check that DecisionEngine was called with the combined results

# \# - Check that MCP update occurred with final scores

# pass \# Requires specific implementation details of the orchestrator
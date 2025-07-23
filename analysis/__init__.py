# File: Oppo/analysis/__init__.py
# Purpose: Initialize the analysis package and make key classes easily accessible

import logging

# Import classes from submodules to allow easier access, e.g., from analysis import DecisionEngine
# Ensure all relevant classes for the LLM-powered version are included
try:
    from .llm_interface import LLMInterface
    from .contradiction_detector import ContradictionDetector
    from .decision_engine import DecisionEngine
    from .disinformation_analyzer import DisinformationAnalyzer
    from .evasion_detector import EvasionDetector
    from .fact_checker import FactChecker
    from .report_generator import ReportGenerator
    ANALYSIS_COMPONENTS_LOADED = True
except ImportError as e:
     logging.error(f"Failed to import one or more analysis components: {e}. Some features may be disabled.")
     ANALYSIS_COMPONENTS_LOADED = False
     # Define dummy classes if needed for type hinting elsewhere
     class LLMInterface: pass
     class ContradictionDetector: pass
     class DecisionEngine: pass
     class DisinformationAnalyzer: pass
     class EvasionDetector: pass
     class FactChecker: pass
     class ReportGenerator: pass


logger = logging.getLogger(__name__)
logger.info("Analysis package initialized.")

# Define what gets imported with 'from analysis import *' (optional)
__all__ = [
    "LLMInterface",
    "ContradictionDetector",
    "DecisionEngine",
    "DisinformationAnalyzer",
    "EvasionDetector",
    "FactChecker",
    "ReportGenerator",
]


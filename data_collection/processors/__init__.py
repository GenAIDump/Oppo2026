# File: Oppo/data_collection/processors/__init__.py
# Purpose: Initialize the processors submodule

import logging

logger = logging.getLogger(__name__)

# Make processor classes directly importable from data_collection.processors
from .fec_processor import FECProcessor
from .congress_processor import CongressProcessor
from .opensecrets_processor import OpenSecretsProcessor
from .house_press_processor import HousePressProcessor
from .campaign_website_processor import CampaignWebsiteProcessor
from .ballotpedia_processor import BallotpediaProcessor

__all__ = [
    "FECProcessor",
    "CongressProcessor",
    "OpenSecretsProcessor",
    "HousePressProcessor",
    "CampaignWebsiteProcessor",
    "BallotpediaProcessor",
]

logger.info("Processors package initialized.")

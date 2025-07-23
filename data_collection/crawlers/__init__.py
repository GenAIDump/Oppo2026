# File: Oppo/data_collection/crawlers/__init__.py
# Purpose: Initialize the crawlers submodule

import logging

logger = logging.getLogger(__name__)

# Make crawler classes directly importable from data_collection.crawlers
from .fec_crawler import FECCrawler
from .congress_crawler import CongressCrawler
from .opensecrets_crawler import OpenSecretsCrawler
from .house_press_crawler import HousePressCrawler
from .campaign_website_crawler import CampaignWebsiteCrawler
from .ballotpedia_crawler import BallotpediaCrawler

__all__ = [
    'FECCrawler',
    'CongressCrawler',
    'OpenSecretsCrawler',
    'HousePressCrawler',
    'CampaignWebsiteCrawler',
    'BallotpediaCrawler'
]

logger.info("Crawlers package initialized.")

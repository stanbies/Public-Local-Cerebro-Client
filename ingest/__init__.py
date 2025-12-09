"""
Ingestion module for Cerebro Companion Client.

Handles:
- XML file parsing (PMF/SUMEHR)
- Patient profile extraction using cerebro_care
- Pseudonymisation pipeline
- Cloud upload preparation
"""

from .processor import XMLProcessor
from .uploader import CloudUploader

__all__ = ["XMLProcessor", "CloudUploader"]

"""
Ingestion module for Cerebro Companion Client.

Handles:
- XML file parsing (PMF/SUMEHR)
- Patient profile extraction using cerebro_care
- Pseudonymisation pipeline
- Cloud upload preparation
"""

from .processor import XMLProcessor, check_ocr_availability
from .uploader import CloudUploader

__all__ = ["XMLProcessor", "CloudUploader", "check_ocr_availability"]

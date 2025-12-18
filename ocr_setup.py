"""
OCR path configuration for bundled Tesseract and Poppler.

This module configures OCR paths at runtime, handling both:
- Development mode (system-installed Tesseract/Poppler)
- Frozen exe mode (bundled binaries)

NOTE: This module intentionally does NOT import pytesseract at module level
to avoid numpy initialization issues with PyInstaller.
"""

import os
import sys
from pathlib import Path


def get_bundle_dir() -> Path:
    """Get the directory where bundled files are located."""
    if getattr(sys, 'frozen', False):
        # Running as compiled exe - files are in _MEIPASS temp directory
        return Path(sys._MEIPASS)
    else:
        # Running as script
        return Path(__file__).parent


def setup_ocr_paths():
    """
    Configure Tesseract and Poppler paths for OCR functionality.
    
    In frozen mode, uses bundled binaries.
    In development mode, uses system-installed binaries.
    
    NOTE: Does not import pytesseract here - just sets environment variables.
    pytesseract will pick up the path from environment when it's imported later.
    """
    bundle_dir = get_bundle_dir()
    is_frozen = getattr(sys, 'frozen', False)
    
    # === TESSERACT SETUP ===
    tesseract_path = None
    
    if is_frozen:
        # Check for bundled Tesseract
        bundled_tesseract = bundle_dir / "tesseract" / "tesseract.exe"
        if bundled_tesseract.exists():
            tesseract_path = str(bundled_tesseract)
            # Also set TESSDATA_PREFIX for language data
            tessdata_dir = bundle_dir / "tesseract" / "tessdata"
            if tessdata_dir.exists():
                os.environ["TESSDATA_PREFIX"] = str(bundle_dir / "tesseract")
    else:
        # Development mode - check common locations
        common_paths = [
            r"C:\Program Files\Tesseract-OCR\tesseract.exe",
            r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
        ]
        for path in common_paths:
            if Path(path).exists():
                tesseract_path = path
                break
    
    if tesseract_path:
        # Set environment variable - pytesseract will use this
        os.environ["TESSERACT_CMD"] = tesseract_path
        print(f"[OCR Setup] Tesseract path set: {tesseract_path}")
    else:
        print("[OCR Setup] Tesseract not found")
    
    # === POPPLER SETUP ===
    poppler_path = None
    
    if is_frozen:
        # Check for bundled Poppler
        bundled_poppler = bundle_dir / "poppler" / "Library" / "bin"
        if not bundled_poppler.exists():
            bundled_poppler = bundle_dir / "poppler" / "bin"
        if bundled_poppler.exists():
            poppler_path = str(bundled_poppler)
    else:
        # Development mode - check common locations
        common_paths = [
            r"C:\Program Files\poppler\Library\bin",
            r"C:\Program Files\poppler-24.08.0\Library\bin",
            r"C:\poppler\Library\bin",
        ]
        for path in common_paths:
            if Path(path).exists():
                poppler_path = path
                break
    
    if poppler_path:
        # Add to PATH so pdf2image can find pdftoppm
        current_path = os.environ.get("PATH", "")
        if poppler_path not in current_path:
            os.environ["PATH"] = poppler_path + os.pathsep + current_path
        print(f"[OCR Setup] Poppler configured: {poppler_path}")
    else:
        print("[OCR Setup] Poppler not found - PDF processing may not work")
    
    return {
        "tesseract_path": tesseract_path,
        "poppler_path": poppler_path,
        "is_frozen": is_frozen,
    }


def configure_pytesseract():
    """
    Configure pytesseract with the correct path.
    Call this AFTER all other imports are done.
    """
    tesseract_path = os.environ.get("TESSERACT_CMD")
    if tesseract_path:
        try:
            import pytesseract
            pytesseract.pytesseract.tesseract_cmd = tesseract_path
            print(f"[OCR Setup] pytesseract configured: {tesseract_path}")
            return True
        except Exception as e:
            print(f"[OCR Setup] pytesseract configuration failed: {e}")
    return False


# Auto-configure paths on import (but don't import pytesseract yet)
_ocr_config = None


def get_ocr_config() -> dict:
    """Get the current OCR configuration."""
    global _ocr_config
    if _ocr_config is None:
        _ocr_config = setup_ocr_paths()
    return _ocr_config

"""
Test OCR functionality with the provided XML files.
"""

import os
import sys
from pathlib import Path

# Add project to path
sys.path.insert(0, str(Path(__file__).parent))

def test_ocr():
    """Test OCR with the example XML files."""
    
    # First check OCR availability
    print("=" * 60)
    print("STEP 1: Checking OCR availability")
    print("=" * 60)
    
    # Try to import get_ocr_status, fall back to direct check
    try:
        from cerebro_care import get_ocr_status
        status = get_ocr_status()
        print(f"OCR Available: {status.get('ocr_available', False)}")
        print(f"Tesseract Path: {status.get('tesseract_path', 'N/A')}")
        if status.get('error'):
            print(f"Error: {status['error']}")
    except ImportError:
        print("get_ocr_status not available in cerebro_care, checking directly...")
        try:
            import pytesseract
            tesseract_path = pytesseract.pytesseract.tesseract_cmd
            print(f"Tesseract Path: {tesseract_path}")
            # Try to get version
            version = pytesseract.get_tesseract_version()
            print(f"Tesseract Version: {version}")
            print("OCR Available: True")
        except Exception as e:
            print(f"OCR Available: False")
            print(f"Error: {e}")
    print()
    
    # Find XML files
    print("=" * 60)
    print("STEP 2: Finding XML files")
    print("=" * 60)
    
    project_dir = Path(__file__).parent
    xml_files = list(project_dir.glob("*.xml"))
    
    for f in xml_files:
        print(f"  - {f.name} ({f.stat().st_size / 1024:.1f} KB)")
    print()
    
    if not xml_files:
        print("No XML files found!")
        return
    
    # Process each file individually to see OCR results
    print("=" * 60)
    print("STEP 3: Processing XML files")
    print("=" * 60)
    
    from cerebro_care import xml_to_patient_profile, profile_to_dict
    
    for xml_file in xml_files:
        print(f"\nProcessing: {xml_file.name}")
        print("-" * 40)
        
        try:
            profile = xml_to_patient_profile(str(xml_file))
            profile_dict = profile_to_dict(profile)
            
            # Check processing metadata for OCR info
            pm = profile_dict.get("processing_metadata", {})
            
            print(f"  Patient: {profile_dict.get('first_name', '?')} {profile_dict.get('last_name', '?')}")
            print(f"  OCR Available: {pm.get('ocr_available', 'N/A')}")
            print(f"  OCR Used: {pm.get('ocr_used', False)}")
            print(f"  PDFs Found: {pm.get('pdfs_found', 0)}")
            print(f"  PDFs with Text: {pm.get('pdfs_with_text', 0)}")
            print(f"  OCR Pages Processed: {pm.get('ocr_pages_processed', 0)}")
            
            # Check for multimedia items
            multimedia = profile_dict.get("multimedia_items", [])
            if multimedia:
                print(f"  Multimedia Items: {len(multimedia)}")
                for i, item in enumerate(multimedia[:5]):  # Show first 5
                    print(f"    [{i+1}] {item.get('title', 'Untitled')} - {item.get('mediatype', '?')}")
                    if item.get('extracted_text'):
                        text_preview = item['extracted_text'][:100].replace('\n', ' ')
                        print(f"        Text: {text_preview}...")
            else:
                print("  Multimedia Items: 0")
                
        except Exception as e:
            print(f"  ERROR: {e}")
            import traceback
            traceback.print_exc()
    
    print()
    print("=" * 60)
    print("TEST COMPLETE")
    print("=" * 60)


if __name__ == "__main__":
    test_ocr()

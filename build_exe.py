"""
Build script for Cerebro Companion Windows executable.

This script:
1. Downloads Tesseract and Poppler if not present
2. Runs PyInstaller to create the executable
3. Optionally creates an installer with Inno Setup

Usage:
    python build_exe.py          # Build exe only
    python build_exe.py --installer  # Build exe + installer
"""

import os
import sys
import shutil
import zipfile
import subprocess
from pathlib import Path
from urllib.request import urlretrieve


# Configuration
PROJECT_DIR = Path(__file__).parent
THIRD_PARTY_DIR = PROJECT_DIR / "third_party"
DIST_DIR = PROJECT_DIR / "dist"

# Download URLs for portable versions
TESSERACT_URL = "https://github.com/UB-Mannheim/tesseract/releases/download/v5.3.3.20231005/tesseract-ocr-w64-setup-5.3.3.20231005.exe"
POPPLER_URL = "https://github.com/oschwartz10612/poppler-windows/releases/download/v24.08.0-0/Release-24.08.0-0.zip"


def download_file(url: str, dest: Path, desc: str = ""):
    """Download a file with progress."""
    print(f"Downloading {desc or url}...")
    
    def progress_hook(block_num, block_size, total_size):
        downloaded = block_num * block_size
        if total_size > 0:
            percent = min(100, downloaded * 100 / total_size)
            print(f"\r  Progress: {percent:.1f}%", end="", flush=True)
    
    urlretrieve(url, dest, progress_hook)
    print()  # newline after progress


def setup_tesseract():
    """Download and extract Tesseract OCR."""
    tesseract_dir = THIRD_PARTY_DIR / "tesseract"
    
    if tesseract_dir.exists() and (tesseract_dir / "tesseract.exe").exists():
        print("[OK] Tesseract already present")
        return True
    
    print("\n=== Setting up Tesseract OCR ===")
    print("NOTE: Tesseract requires manual installation for bundling.")
    print("Please install Tesseract from: https://github.com/UB-Mannheim/tesseract/releases")
    print(f"Then copy the installation folder to: {tesseract_dir}")
    print("\nAlternatively, if Tesseract is already installed on this system,")
    print("the exe will use the system installation in development mode.")
    
    # Check if system Tesseract exists
    system_tesseract = Path(r"C:\Program Files\Tesseract-OCR")
    if system_tesseract.exists():
        print(f"\n[INFO] Found system Tesseract at {system_tesseract}")
        print("Copying to third_party for bundling...")
        
        tesseract_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(system_tesseract, tesseract_dir)
        print("[OK] Tesseract copied successfully")
        return True
    
    return False


def setup_poppler():
    """Download and extract Poppler for PDF processing."""
    poppler_dir = THIRD_PARTY_DIR / "poppler"
    
    if poppler_dir.exists() and (poppler_dir / "Library" / "bin" / "pdftoppm.exe").exists():
        print("[OK] Poppler already present")
        return True
    
    print("\n=== Setting up Poppler ===")
    
    THIRD_PARTY_DIR.mkdir(parents=True, exist_ok=True)
    zip_path = THIRD_PARTY_DIR / "poppler.zip"
    
    try:
        download_file(POPPLER_URL, zip_path, "Poppler")
        
        print("Extracting Poppler...")
        with zipfile.ZipFile(zip_path, 'r') as zf:
            # Extract to temp location first
            temp_extract = THIRD_PARTY_DIR / "poppler_temp"
            zf.extractall(temp_extract)
            
            # Find the extracted folder (usually named poppler-xx.xx.x)
            extracted_folders = list(temp_extract.iterdir())
            if extracted_folders:
                extracted_folder = extracted_folders[0]
                # Move to final location
                if poppler_dir.exists():
                    shutil.rmtree(poppler_dir)
                shutil.move(str(extracted_folder), str(poppler_dir))
            
            # Cleanup
            if temp_extract.exists():
                shutil.rmtree(temp_extract)
        
        zip_path.unlink()
        print("[OK] Poppler extracted successfully")
        return True
        
    except Exception as e:
        print(f"[ERROR] Failed to setup Poppler: {e}")
        return False


def build_exe():
    """Build the executable with PyInstaller."""
    print("\n=== Building Executable ===")
    
    spec_file = PROJECT_DIR / "cerebro_companion.spec"
    
    if not spec_file.exists():
        print(f"[ERROR] Spec file not found: {spec_file}")
        return False
    
    # Clean previous build
    build_dir = PROJECT_DIR / "build"
    if build_dir.exists():
        print("Cleaning previous build...")
        shutil.rmtree(build_dir)
    
    # Run PyInstaller
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--clean",
        "--noconfirm",
        str(spec_file)
    ]
    
    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=PROJECT_DIR)
    
    if result.returncode != 0:
        print("[ERROR] PyInstaller failed")
        return False
    
    # Verify output
    exe_path = DIST_DIR / "CerebroCompanion" / "CerebroCompanion.exe"
    if exe_path.exists():
        print(f"[OK] Executable created: {exe_path}")
        return True
    else:
        print("[ERROR] Executable not found after build")
        return False


def create_installer():
    """Create Windows installer with Inno Setup."""
    print("\n=== Creating Installer ===")
    
    # Check if Inno Setup is installed
    inno_paths = [
        Path(r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe"),
        Path(r"C:\Program Files\Inno Setup 6\ISCC.exe"),
    ]
    
    iscc_path = None
    for path in inno_paths:
        if path.exists():
            iscc_path = path
            break
    
    if not iscc_path:
        print("[WARNING] Inno Setup not found. Skipping installer creation.")
        print("Install from: https://jrsoftware.org/isdl.php")
        return False
    
    iss_file = PROJECT_DIR / "installer.iss"
    if not iss_file.exists():
        print(f"[ERROR] Installer script not found: {iss_file}")
        return False
    
    cmd = [str(iscc_path), str(iss_file)]
    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd, cwd=PROJECT_DIR)
    
    if result.returncode != 0:
        print("[ERROR] Inno Setup failed")
        return False
    
    print("[OK] Installer created successfully")
    return True


def main():
    """Main build process."""
    print("=" * 60)
    print("  Cerebro Companion Build Script")
    print("=" * 60)
    
    create_installer_flag = "--installer" in sys.argv
    
    # Step 1: Setup OCR dependencies
    tesseract_ok = setup_tesseract()
    poppler_ok = setup_poppler()
    
    if not tesseract_ok:
        print("\n[WARNING] Tesseract not bundled - OCR may not work on target machines")
    
    if not poppler_ok:
        print("\n[WARNING] Poppler not bundled - PDF processing may not work")
    
    # Step 2: Build executable
    if not build_exe():
        print("\n[FAILED] Build failed")
        return 1
    
    # Step 3: Create installer (optional)
    if create_installer_flag:
        create_installer()
    
    print("\n" + "=" * 60)
    print("  Build Complete!")
    print("=" * 60)
    print(f"\nExecutable: {DIST_DIR / 'CerebroCompanion' / 'CerebroCompanion.exe'}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())

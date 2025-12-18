"""
Cerebro Companion Client - Main Entry Point

A local FastAPI application for secure medical data processing.
Runs on http://127.0.0.1:18421 and opens the browser automatically.
"""

import os
import sys
import json
import asyncio
import webbrowser
from pathlib import Path
from typing import Optional
from contextlib import asynccontextmanager
from datetime import datetime

# Configure OCR paths before importing anything that uses them
# NOTE: This only sets environment variables, doesn't import pytesseract yet
from ocr_setup import setup_ocr_paths, get_ocr_config
_ocr_config = setup_ocr_paths()

from fastapi import FastAPI, Request, UploadFile, File, Form, HTTPException, Depends
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware

from config import config
from auth import AuthManager
from crypto import KeyManager
from crypto.vault import LocalVaultCache
from crypto.passphrase import PassphraseDeriver
from ingest import XMLProcessor, CloudUploader
from ingest.processor import create_mapping_for_vault
from updater import UpdateChecker

__version__ = "1.0.0"


# Global state
class AppState:
    """Application state container."""
    key_manager: Optional[KeyManager] = None
    auth_manager: Optional[AuthManager] = None
    vault_cache: Optional[LocalVaultCache] = None
    update_checker: Optional[UpdateChecker] = None
    processing_logs: list[dict] = []
    current_mappings: dict = {}  # In-memory only, loaded from encrypted local storage
    _passphrase_key: Optional[bytes] = None  # Derived key for local encryption
    _update_dismissed: bool = False  # User dismissed the update popup
    
    def set_passphrase_key(self, key: bytes):
        """Set the passphrase-derived key for local vault encryption."""
        self._passphrase_key = key
    
    def save_mappings_locally(self):
        """Save current mappings to encrypted local storage."""
        if self._passphrase_key and self.vault_cache and self.current_mappings:
            self.vault_cache.save(self.current_mappings, self._passphrase_key)
            self.add_log("info", "Mappings saved locally", f"{len(self.current_mappings)} patient mapping(s) encrypted")
    
    def load_mappings_locally(self) -> bool:
        """Load mappings from encrypted local storage."""
        if self._passphrase_key and self.vault_cache:
            loaded = self.vault_cache.load(self._passphrase_key)
            if loaded:
                self.current_mappings = loaded
                self.add_log("info", "Mappings loaded", f"{len(loaded)} patient mapping(s) decrypted from local storage")
                return True
        return False
    
    def add_log(self, level: str, message: str, details: str = ""):
        """Add a log entry."""
        self.processing_logs.append({
            "timestamp": datetime.now().isoformat(),
            "level": level,
            "message": message,
            "details": details,
        })
        # Keep only last 100 logs
        if len(self.processing_logs) > 100:
            self.processing_logs = self.processing_logs[-100:]
    
    def clear_sensitive_data(self):
        """Clear all sensitive data from memory."""
        self.current_mappings = {}
        self._passphrase_key = None
        if self.key_manager:
            self.key_manager.lock()


app_state = AppState()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Startup
    app_state.key_manager = KeyManager(config.keys_dir)
    app_state.auth_manager = AuthManager(config.CLOUD_API_URL, config.jwt_path)
    app_state.vault_cache = LocalVaultCache(config.mapping_cache_path)
    app_state.update_checker = UpdateChecker(__version__)
    
    app_state.add_log("info", "Cerebro Companion started", f"Server running on http://{config.HOST}:{config.PORT}")
    
    # Check for updates in background
    asyncio.create_task(check_for_updates_on_startup())
    
    yield
    
    # Shutdown - clear sensitive data
    app_state.clear_sensitive_data()
    app_state.add_log("info", "Cerebro Companion stopped", "Sensitive data cleared from memory")


# Create FastAPI app
app = FastAPI(
    title="Cerebro Companion",
    description="Local client for secure medical data processing",
    version=__version__,
    lifespan=lifespan,
)

# CORS middleware (allow frontend and local client UI)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for local development
    allow_credentials=False,  # Must be False when allow_origins is "*"
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

# Static files and templates
# Handle PyInstaller frozen exe - files are in _MEIPASS temp directory
if getattr(sys, 'frozen', False):
    # Running as compiled exe
    bundle_dir = Path(sys._MEIPASS)
else:
    # Running as script
    bundle_dir = Path(__file__).parent

static_dir = bundle_dir / "static"
templates_dir = bundle_dir / "templates"

# Only create dirs if running as script (not frozen)
if not getattr(sys, 'frozen', False):
    static_dir.mkdir(exist_ok=True)
    templates_dir.mkdir(exist_ok=True)

app.mount("/static", StaticFiles(directory=static_dir), name="static")
templates = Jinja2Templates(directory=templates_dir)


# ============================================================================
# UI Routes
# ============================================================================

@app.get("/", response_class=HTMLResponse)
async def root():
    """Redirect to UI."""
    return RedirectResponse(url="/ui")


@app.get("/ui", response_class=HTMLResponse)
async def login_page(request: Request):
    """Login page."""
    # If already authenticated, redirect to dashboard
    if app_state.auth_manager and app_state.auth_manager.is_authenticated:
        return RedirectResponse(url="/ui/dashboard")
    
    return templates.TemplateResponse("login.html", {"request": request})


@app.get("/ui/dashboard", response_class=HTMLResponse)
async def dashboard_page(request: Request):
    """Dashboard page."""
    if not app_state.auth_manager or not app_state.auth_manager.is_authenticated:
        return RedirectResponse(url="/ui")
    
    session = app_state.auth_manager.current_session
    key_status = "unlocked" if app_state.key_manager.is_unlocked else "locked"
    has_keys = app_state.key_manager.has_keys
    
    return templates.TemplateResponse("dashboard.html", {
        "request": request,
        "username": session.username,
        "fullname": session.fullname,
        "key_status": key_status,
        "has_keys": has_keys,
    })


# ============================================================================
# Authentication API
# ============================================================================

@app.post("/api/auth/login")
async def api_login(request: Request):
    """Handle login request."""
    data = await request.json()
    username = data.get("username", "")
    password = data.get("password", "")
    
    if not username or not password:
        raise HTTPException(status_code=400, detail="Username and password required")
    
    success, message = await app_state.auth_manager.login(username, password)
    
    if success:
        app_state.add_log("info", "Login successful", f"User: {username}")
        return {"success": True, "message": message}
    else:
        app_state.add_log("warning", "Login failed", message)
        raise HTTPException(status_code=401, detail=message)


@app.post("/api/auth/logout")
async def api_logout():
    """Handle logout request."""
    if app_state.auth_manager:
        app_state.auth_manager.logout()
    app_state.clear_sensitive_data()
    app_state.add_log("info", "Logout successful", "Session cleared")
    return {"success": True, "message": "Logged out"}


# ============================================================================
# Key Management API
# ============================================================================

@app.get("/api/keys/status")
async def get_key_status():
    """Get current key status."""
    return {
        "has_keys": app_state.key_manager.has_keys,
        "is_unlocked": app_state.key_manager.is_unlocked,
    }


@app.post("/api/keys/generate")
async def generate_keys(request: Request):
    """Generate new keypair."""
    data = await request.json()
    passphrase = data.get("passphrase", "")
    
    if not passphrase or len(passphrase) < 8:
        raise HTTPException(status_code=400, detail="Passphrase must be at least 8 characters")
    
    if app_state.key_manager.has_keys:
        raise HTTPException(status_code=400, detail="Keys already exist. Delete existing keys first.")
    
    try:
        public_key_pem, public_key_raw = app_state.key_manager.generate_keypair(passphrase)
        
        # Set the passphrase key using the stored salt (for vault encryption)
        salt = app_state.key_manager.get_stored_salt()
        if salt:
            derived_key, _ = PassphraseDeriver.derive_key(passphrase, salt)
            app_state.set_passphrase_key(derived_key)
            app_state.auth_manager.set_encryption_key(derived_key)
        
        # Register public key with cloud
        if app_state.auth_manager and app_state.auth_manager.is_authenticated:
            uploader = CloudUploader(
                config.CLOUD_API_URL,
                app_state.auth_manager.current_session.access_token
            )
            result = await uploader.register_public_key(public_key_pem.decode("utf-8"))
            await uploader.close()
            
            if not result.success:
                app_state.add_log("warning", "Key registration failed", result.message)
        
        app_state.add_log("info", "Keys generated", "New X25519 keypair created")
        
        return {
            "success": True,
            "message": "Keys generated successfully",
            "public_key": public_key_pem.decode("utf-8"),
        }
        
    except Exception as e:
        app_state.add_log("error", "Key generation failed", str(e))
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/keys/unlock")
async def unlock_keys(request: Request):
    """Unlock private key with passphrase."""
    data = await request.json()
    passphrase = data.get("passphrase", "")
    
    if not passphrase:
        raise HTTPException(status_code=400, detail="Passphrase required")
    
    if not app_state.key_manager.has_keys:
        raise HTTPException(status_code=400, detail="No keys found. Generate keys first.")
    
    success = app_state.key_manager.unlock(passphrase)
    
    if success:
        # Derive encryption key using the SAME salt as the private key
        # This ensures consistent key derivation for vault encryption
        salt = app_state.key_manager.get_stored_salt()
        if salt:
            derived_key, _ = PassphraseDeriver.derive_key(passphrase, salt)
        else:
            # Fallback: generate new salt (won't be able to load old mappings)
            derived_key, _ = PassphraseDeriver.derive_key(passphrase)
        
        app_state.set_passphrase_key(derived_key)
        app_state.auth_manager.set_encryption_key(derived_key)
        
        # Load existing mappings from local encrypted storage
        loaded = app_state.load_mappings_locally()
        
        app_state.add_log("info", "Keys unlocked", f"Private key loaded. Mappings loaded: {loaded}")
        return {"success": True, "message": "Keys unlocked", "mappings_loaded": len(app_state.current_mappings)}
    else:
        app_state.add_log("warning", "Unlock failed", "Invalid passphrase")
        raise HTTPException(status_code=401, detail="Invalid passphrase")


@app.post("/api/keys/lock")
async def lock_keys():
    """Lock private key (clear from memory)."""
    app_state.key_manager.lock()
    app_state.add_log("info", "Keys locked", "Private key cleared from memory")
    return {"success": True, "message": "Keys locked"}


# ============================================================================
# File Ingestion API
# ============================================================================

@app.post("/api/ingest/upload-file")
async def upload_file(file: UploadFile = File(...)):
    """Upload and process a single XML file."""
    if not app_state.auth_manager or not app_state.auth_manager.is_authenticated:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    if not app_state.key_manager.is_unlocked:
        raise HTTPException(status_code=400, detail="Keys must be unlocked first")
    
    # Validate file
    filename = file.filename or "unknown.xml"
    ext = Path(filename).suffix.lower()
    if ext not in [".xml", ".pmf", ".sumehr"]:
        raise HTTPException(status_code=400, detail=f"Invalid file type: {ext}")
    
    content = await file.read()
    
    app_state.add_log("info", f"Processing file: {filename}", "Starting ingestion pipeline")
    
    # Process file
    processor = XMLProcessor(
        salt=config.PSEUDONYMISATION_SALT,
        progress_callback=lambda p: app_state.add_log("info", p.message, f"Stage: {p.stage}, Progress: {p.progress*100:.0f}%")
    )
    
    result = processor.process_single_file(filename, content)
    
    if not result.success:
        app_state.add_log("error", "Processing failed", "; ".join(result.errors))
        raise HTTPException(status_code=400, detail="; ".join(result.errors))
    
    # Store mappings in memory and save encrypted locally (NEVER sent to cloud)
    vault_mapping = create_mapping_for_vault(result.mappings)
    
    # DEBUG: Log mapping details
    print(f"\n=== MAPPING DEBUG (single file) ===")
    print(f"New mappings from this file: {len(vault_mapping)}")
    print(f"New pseudo_ids: {list(vault_mapping.keys())}")
    print(f"Current mappings before update: {len(app_state.current_mappings)}")
    print(f"Existing pseudo_ids: {list(app_state.current_mappings.keys())}")
    
    app_state.current_mappings.update(vault_mapping)
    
    print(f"Current mappings after update: {len(app_state.current_mappings)}")
    print(f"=== END DEBUG ===\n")
    
    # Save mappings to encrypted local storage
    app_state.save_mappings_locally()
    
    # Upload ONLY anonymised patient profiles and care tasks to cloud (no mappings!)
    app_state.add_log("info", "Uploading to cloud", "Sending anonymised patient data only")
    
    uploader = CloudUploader(
        config.CLOUD_API_URL,
        app_state.auth_manager.current_session.access_token
    )
    
    try:
        # Upload patients and care tasks (anonymised data only)
        patient_result = await uploader.upload_patients(result.profiles, result.care_tasks)
        
        if patient_result.success:
            app_state.add_log("info", "Patients uploaded", patient_result.message)
        else:
            app_state.add_log("warning", "Patient upload issues", "; ".join(patient_result.errors))
        
    finally:
        await uploader.close()
    
    app_state.add_log("info", f"Completed: {filename}", f"Processed {result.patient_count} patient(s) in {result.processing_time_ms}ms")
    
    return {
        "success": True,
        "message": f"Processed {result.patient_count} patient(s)",
        "patient_count": result.patient_count,
        "task_count": len(result.care_tasks),
        "processing_time_ms": result.processing_time_ms,
    }


@app.post("/api/ingest/upload-files")
async def upload_files(files: list[UploadFile] = File(...)):
    """Upload and process multiple XML files."""
    if not app_state.auth_manager or not app_state.auth_manager.is_authenticated:
        raise HTTPException(status_code=401, detail="Not authenticated")
    
    if not app_state.key_manager.is_unlocked:
        raise HTTPException(status_code=400, detail="Keys must be unlocked first")
    
    # Collect files
    file_data = []
    for file in files:
        filename = file.filename or "unknown.xml"
        ext = Path(filename).suffix.lower()
        if ext in [".xml", ".pmf", ".sumehr"]:
            content = await file.read()
            file_data.append((filename, content))
    
    if not file_data:
        raise HTTPException(status_code=400, detail="No valid XML files provided")
    
    app_state.add_log("info", f"Processing {len(file_data)} files", "Starting batch ingestion")
    
    # Process files
    processor = XMLProcessor(
        salt=config.PSEUDONYMISATION_SALT,
        progress_callback=lambda p: app_state.add_log("info", p.message, f"Stage: {p.stage}")
    )
    
    result = processor.process_files(file_data)
    
    if not result.success:
        app_state.add_log("error", "Processing failed", "; ".join(result.errors))
        raise HTTPException(status_code=400, detail="; ".join(result.errors))
    
    # Store mappings in memory and save encrypted locally (NEVER sent to cloud)
    vault_mapping = create_mapping_for_vault(result.mappings)
    
    # DEBUG: Log mapping details
    print(f"\n=== MAPPING DEBUG (batch) ===")
    print(f"New mappings from batch: {len(vault_mapping)}")
    print(f"New pseudo_ids: {list(vault_mapping.keys())}")
    print(f"Current mappings before update: {len(app_state.current_mappings)}")
    print(f"Existing pseudo_ids: {list(app_state.current_mappings.keys())}")
    
    app_state.current_mappings.update(vault_mapping)
    
    print(f"Current mappings after update: {len(app_state.current_mappings)}")
    print(f"=== END DEBUG ===\n")
    
    # Save mappings to encrypted local storage
    app_state.save_mappings_locally()
    
    # Upload ONLY anonymised patient profiles and care tasks to cloud
    uploader = CloudUploader(
        config.CLOUD_API_URL,
        app_state.auth_manager.current_session.access_token
    )
    
    try:
        await uploader.upload_patients(result.profiles, result.care_tasks)
    finally:
        await uploader.close()
    
    app_state.add_log("info", "Batch completed", f"Processed {result.patient_count} patient(s)")
    
    return {
        "success": True,
        "message": f"Processed {result.patient_count} patient(s) from {len(file_data)} files",
        "patient_count": result.patient_count,
        "task_count": len(result.care_tasks),
        "processing_time_ms": result.processing_time_ms,
    }


# ============================================================================
# Logs API
# ============================================================================

@app.get("/api/logs")
async def get_logs(limit: int = 50):
    """Get recent processing logs."""
    logs = app_state.processing_logs[-limit:]
    return {"logs": logs}


@app.delete("/api/logs")
async def clear_logs():
    """Clear processing logs."""
    app_state.processing_logs = []
    return {"success": True, "message": "Logs cleared"}


# ============================================================================
# Mapping Resolution API (for UI identity display)
# ============================================================================

@app.get("/api/mappings/resolve/{pseudo_id}")
async def resolve_mapping(pseudo_id: str):
    """
    Resolve a pseudo ID to patient identity (from in-memory cache only).
    This data never leaves the local machine.
    """
    if not app_state.key_manager.is_unlocked:
        raise HTTPException(status_code=400, detail="Keys must be unlocked")
    
    mapping = app_state.current_mappings.get(pseudo_id)
    if mapping:
        return {"found": True, "mapping": mapping}
    
    return {"found": False, "mapping": None}


@app.get("/api/mappings/email/{pseudo_id}")
async def get_patient_email(pseudo_id: str):
    """
    Get the email address(es) for a patient by pseudo ID.
    This data never leaves the local machine.
    """
    if not app_state.key_manager.is_unlocked:
        raise HTTPException(status_code=400, detail="Keys must be unlocked")
    
    mapping = app_state.current_mappings.get(pseudo_id)
    if mapping:
        emails = mapping.get("emails", [])
        return {
            "found": True,
            "pseudo_id": pseudo_id,
            "emails": emails,
            "primary_email": emails[0] if emails else None,
        }
    
    return {"found": False, "pseudo_id": pseudo_id, "emails": [], "primary_email": None}


@app.post("/api/mappings/reload")
async def reload_mappings():
    """
    Reload mappings from encrypted local storage.
    Mappings are stored locally only, never on the cloud.
    """
    if not app_state.key_manager.is_unlocked:
        raise HTTPException(status_code=400, detail="Keys must be unlocked")
    
    if not app_state._passphrase_key:
        raise HTTPException(status_code=400, detail="Passphrase key not available")
    
    success = app_state.load_mappings_locally()
    
    if success:
        return {
            "success": True,
            "message": f"Loaded {len(app_state.current_mappings)} patient mappings from local storage",
            "patient_count": len(app_state.current_mappings),
        }
    else:
        return {
            "success": True,
            "message": "No local mappings found",
            "patient_count": 0,
        }


@app.get("/api/mappings/count")
async def get_mappings_count():
    """Get the count of currently loaded mappings."""
    return {
        "count": len(app_state.current_mappings),
        "keys_unlocked": app_state.key_manager.is_unlocked if app_state.key_manager else False,
    }


@app.delete("/api/mappings")
async def delete_all_mappings():
    """Delete all mappings from memory and local storage."""
    if not app_state.key_manager.is_unlocked:
        raise HTTPException(status_code=400, detail="Keys must be unlocked")
    
    count = len(app_state.current_mappings)
    
    # Clear in-memory mappings
    app_state.current_mappings = {}
    
    # Clear local encrypted storage
    if app_state.vault_cache:
        app_state.vault_cache.clear()
    
    app_state.add_log("info", "Mappings verwijderd", f"{count} patiënt mapping(s) verwijderd")
    
    return {
        "success": True,
        "message": f"{count} mapping(s) verwijderd",
        "deleted_count": count,
    }


# ============================================================================
# Version API
# ============================================================================

@app.get("/api/version")
async def get_version():
    """Get current application version."""
    return {
        "version": __version__,
        "app_name": "Cerebro Companion",
    }


# ============================================================================
# Diagnostics API
# ============================================================================

@app.get("/api/diagnostics/ocr")
async def check_ocr():
    """Check OCR (Tesseract) availability for PDF text extraction."""
    from cerebro_care import get_ocr_status
    status = get_ocr_status()
    return {
        "ocr_available": status.get("ocr_available", False),
        "tesseract_path": status.get("tesseract_path"),
        "error": status.get("error"),
    }


# ============================================================================
# Update API
# ============================================================================

async def check_for_updates_on_startup():
    """Check for updates when the application starts."""
    await asyncio.sleep(2)  # Wait a bit for the app to fully start
    if app_state.update_checker:
        try:
            info = await app_state.update_checker.check_for_updates()
            if info.update_available:
                app_state.add_log(
                    "info", 
                    "Update available", 
                    f"New version {info.latest_version} is available (current: {info.current_version})"
                )
        except Exception as e:
            app_state.add_log("warning", "Update check failed", str(e))


@app.get("/api/update/check")
async def check_for_updates():
    """Check if a new version is available."""
    if not app_state.update_checker:
        return {"update_available": False, "error": "Update checker not initialized"}
    
    try:
        info = await app_state.update_checker.check_for_updates()
        return {
            "update_available": info.update_available,
            "current_version": info.current_version,
            "latest_version": info.latest_version,
            "release_notes": info.release_notes,
            "release_url": info.release_url,
            "published_at": info.published_at,
            "has_new_commits": getattr(info, 'has_new_commits', False),
            "dismissed": app_state._update_dismissed,
        }
    except Exception as e:
        return {"update_available": False, "error": str(e)}


@app.get("/api/update/status")
async def get_update_status():
    """Get cached update status without making a new request."""
    if not app_state.update_checker:
        return {"update_available": False}
    
    info = app_state.update_checker.get_cached_info()
    if info:
        return {
            "update_available": info.update_available,
            "current_version": info.current_version,
            "latest_version": info.latest_version,
            "release_notes": info.release_notes,
            "release_url": info.release_url,
            "has_new_commits": getattr(info, 'has_new_commits', False),
            "dismissed": app_state._update_dismissed,
        }
    return {"update_available": False, "dismissed": app_state._update_dismissed}


@app.post("/api/update/dismiss")
async def dismiss_update():
    """Dismiss the update notification for this session."""
    app_state._update_dismissed = True
    return {"ok": True}


@app.post("/api/update/trigger")
async def trigger_update():
    """
    Trigger the update process.
    In Docker, this signals that the container should be restarted with new image.
    Returns instructions for the user.
    """
    from updater import is_running_in_docker, get_update_command
    
    in_docker = is_running_in_docker()
    
    if in_docker:
        # In Docker, we need to signal an external process to update
        # Create a flag file that start.bat can check
        flag_path = Path("/app/data/.update_requested")
        try:
            flag_path.write_text("update")
            app_state.add_log("info", "Update requested", "Container will be updated on next restart")
            return {
                "ok": True,
                "message": "Update aangevraagd. De applicatie wordt nu afgesloten voor de update.",
                "action": "restart_required",
                "command": get_update_command(),
            }
        except Exception as e:
            return {"ok": False, "error": str(e)}
    else:
        return {
            "ok": True,
            "message": "Update handmatig uitvoeren",
            "action": "manual",
            "command": get_update_command(),
        }


# ============================================================================
# Heartbeat API
# ============================================================================

# Track last heartbeat time
_last_heartbeat: Optional[datetime] = None
_shutdown_requested: bool = False


@app.post("/api/heartbeat")
async def heartbeat():
    """Receive heartbeat from browser to know it's still open."""
    global _last_heartbeat
    _last_heartbeat = datetime.now()
    return {"ok": True}


@app.post("/api/shutdown-signal")
async def shutdown_signal():
    """
    Receive shutdown signal when browser tab is closing.
    This is now a no-op - we only shutdown via explicit /api/shutdown.
    """
    # Don't auto-shutdown on tab close - too aggressive
    return {"ok": True}


@app.post("/api/shutdown")
async def shutdown_app():
    """
    Explicitly shutdown the application.
    Called when user clicks the Exit button.
    """
    global _shutdown_requested
    
    is_frozen = getattr(sys, 'frozen', False)
    if not _shutdown_requested:
        _shutdown_requested = True
        app_state.add_log("info", "Shutdown requested", "Application shutting down...")
        print("[APP] Shutdown requested by user")
        
        # Schedule shutdown after a short delay
        async def delayed_shutdown():
            await asyncio.sleep(1)
            if is_frozen:
                os._exit(0)
            else:
                # In dev mode, just stop gracefully
                import signal
                os.kill(os.getpid(), signal.SIGTERM)
        
        asyncio.create_task(delayed_shutdown())
    
    return {"ok": True, "message": "Shutting down..."}


@app.post("/api/visibility-hidden")
async def visibility_hidden():
    """Browser tab became hidden - don't shutdown immediately, just log."""
    # We don't shutdown on visibility change, only on actual close
    return {"ok": True}


# ============================================================================
# Main Entry Point
# ============================================================================

def open_browser():
    """Open the browser after a short delay."""
    import time
    time.sleep(1)
    webbrowser.open(f"http://127.0.0.1:{config.PORT}/ui")


if __name__ == "__main__":
    import uvicorn
    import threading
    import logging
    
    # Check if running in Docker (don't open browser)
    in_docker = os.path.exists('/.dockerenv') or os.environ.get('DOCKER_CONTAINER', False)
    
    # Check if running as frozen exe
    is_frozen = getattr(sys, 'frozen', False)
    
    # Fix for PyInstaller windowed mode: sys.stdout/stderr are None
    # This causes uvicorn's logging to fail on isatty() check
    if is_frozen and sys.stdout is None:
        import io
        sys.stdout = io.StringIO()
        sys.stderr = io.StringIO()
    
    # In Docker, bind to 0.0.0.0 to accept external connections
    host = "0.0.0.0" if in_docker else config.HOST
    
    if not in_docker:
        # Start browser opener in background thread (only when not in Docker)
        browser_thread = threading.Thread(target=open_browser, daemon=True)
        browser_thread.start()
    
    # Run the server
    # In frozen mode, pass the app object directly (string import doesn't work)
    # In development mode, use string for hot reload capability
    if is_frozen:
        uvicorn.run(
            app,
            host=host,
            port=config.PORT,
            log_level="info",
        )
    else:
        uvicorn.run(
            "main:app",
            host=host,
            port=config.PORT,
            reload=False,
            log_level="info",
        )

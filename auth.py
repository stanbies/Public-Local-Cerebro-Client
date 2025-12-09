"""
Authentication handling for Cerebro Companion Client.

Manages:
- Cloud login via Django API
- JWT storage and refresh
- Session management
"""

import os
import json
import base64
import httpx
from pathlib import Path
from typing import Optional
from datetime import datetime, timedelta
from dataclasses import dataclass

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from config import config


@dataclass
class UserSession:
    """Represents an authenticated user session."""
    access_token: str
    refresh_token: str
    username: str
    fullname: str
    role: Optional[str] = None
    is_staff: bool = False
    is_superuser: bool = False
    expires_at: Optional[datetime] = None


class AuthManager:
    """Manages authentication with the Cerebro cloud."""
    
    NONCE_LEN = 12
    
    def __init__(self, api_base_url: str, jwt_storage_path: Path):
        """
        Initialize the auth manager.
        
        Args:
            api_base_url: Base URL of the Cerebro cloud API
            jwt_storage_path: Path to store encrypted JWT
        """
        self.api_base_url = api_base_url.rstrip("/")
        self.jwt_storage_path = jwt_storage_path
        self._session: Optional[UserSession] = None
        self._encryption_key: Optional[bytes] = None
    
    def set_encryption_key(self, key: bytes):
        """Set the encryption key for JWT storage (derived from passphrase)."""
        self._encryption_key = key
    
    @property
    def is_authenticated(self) -> bool:
        """Check if user is currently authenticated."""
        return self._session is not None
    
    @property
    def current_session(self) -> Optional[UserSession]:
        """Get the current session."""
        return self._session
    
    async def login(self, username: str, password: str) -> tuple[bool, str]:
        """
        Login to the Cerebro cloud.
        
        Args:
            username: User's username or email
            password: User's password
            
        Returns:
            Tuple of (success, message)
        """
        try:
            url = f"{self.api_base_url}/api/token/"
            print(f"[AUTH] Attempting login to: {url}")
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    url,
                    json={"username": username, "password": password},
                )
                
                print(f"[AUTH] Response status: {response.status_code}")
                
                if response.status_code == 200:
                    data = response.json()
                    
                    # Parse JWT payload
                    access_token = data["access"]
                    refresh_token = data["refresh"]
                    
                    # Decode JWT payload (without verification - server already verified)
                    payload_b64 = access_token.split(".")[1]
                    # Add padding if needed
                    payload_b64 += "=" * (4 - len(payload_b64) % 4)
                    payload = json.loads(base64.urlsafe_b64decode(payload_b64))
                    
                    # Create session
                    self._session = UserSession(
                        access_token=access_token,
                        refresh_token=refresh_token,
                        username=payload.get("username", username),
                        fullname=payload.get("fullname", ""),
                        role=payload.get("role"),
                        is_staff=payload.get("is_staff", False),
                        is_superuser=payload.get("is_superuser", False),
                        expires_at=datetime.fromtimestamp(payload.get("exp", 0)) if "exp" in payload else None,
                    )
                    
                    # Store encrypted JWT if we have an encryption key
                    if self._encryption_key:
                        self._save_jwt()
                    
                    return True, "Login successful"
                    
                elif response.status_code == 401:
                    try:
                        error_data = response.json()
                        detail = error_data.get("detail", "Invalid username or password")
                        print(f"[AUTH] 401 error detail: {error_data}")
                    except Exception:
                        detail = "Invalid username or password"
                    return False, detail
                else:
                    try:
                        error_data = response.json()
                        print(f"[AUTH] Error response: {error_data}")
                    except Exception:
                        print(f"[AUTH] Error response text: {response.text}")
                    return False, f"Login failed: {response.status_code}"
                    
        except httpx.RequestError as e:
            return False, f"Network error: {str(e)}"
        except Exception as e:
            return False, f"Unexpected error: {str(e)}"
    
    async def refresh_token(self) -> bool:
        """
        Refresh the access token.
        
        Returns:
            True if successful, False otherwise
        """
        if not self._session:
            return False
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{self.api_base_url}/api/token/refresh/",
                    json={"refresh": self._session.refresh_token},
                )
                
                if response.status_code == 200:
                    data = response.json()
                    self._session.access_token = data["access"]
                    
                    # Update expiry
                    payload_b64 = data["access"].split(".")[1]
                    payload_b64 += "=" * (4 - len(payload_b64) % 4)
                    payload = json.loads(base64.urlsafe_b64decode(payload_b64))
                    self._session.expires_at = datetime.fromtimestamp(payload.get("exp", 0))
                    
                    if self._encryption_key:
                        self._save_jwt()
                    
                    return True
                    
        except Exception:
            pass
        
        return False
    
    def logout(self):
        """Logout and clear session."""
        self._session = None
        if self.jwt_storage_path.exists():
            self.jwt_storage_path.unlink()
    
    def _save_jwt(self):
        """Save JWT to encrypted storage."""
        if not self._encryption_key or not self._session:
            return
        
        data = {
            "access_token": self._session.access_token,
            "refresh_token": self._session.refresh_token,
            "username": self._session.username,
            "fullname": self._session.fullname,
            "role": self._session.role,
            "is_staff": self._session.is_staff,
            "is_superuser": self._session.is_superuser,
        }
        
        plaintext = json.dumps(data).encode("utf-8")
        nonce = os.urandom(self.NONCE_LEN)
        aesgcm = AESGCM(self._encryption_key)
        ciphertext = aesgcm.encrypt(nonce, plaintext, None)
        
        storage_data = {
            "nonce": base64.b64encode(nonce).decode("ascii"),
            "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
        }
        
        self.jwt_storage_path.write_text(json.dumps(storage_data))
    
    def load_saved_jwt(self) -> bool:
        """
        Load JWT from encrypted storage.
        
        Returns:
            True if successful, False otherwise
        """
        if not self._encryption_key or not self.jwt_storage_path.exists():
            return False
        
        try:
            storage_data = json.loads(self.jwt_storage_path.read_text())
            nonce = base64.b64decode(storage_data["nonce"])
            ciphertext = base64.b64decode(storage_data["ciphertext"])
            
            aesgcm = AESGCM(self._encryption_key)
            plaintext = aesgcm.decrypt(nonce, ciphertext, None)
            data = json.loads(plaintext.decode("utf-8"))
            
            self._session = UserSession(
                access_token=data["access_token"],
                refresh_token=data["refresh_token"],
                username=data["username"],
                fullname=data["fullname"],
                role=data.get("role"),
                is_staff=data.get("is_staff", False),
                is_superuser=data.get("is_superuser", False),
            )
            
            return True
            
        except Exception:
            return False
    
    def is_token_expired(self) -> bool:
        """Check if the current token is expired or about to expire."""
        if not self._session or not self._session.expires_at:
            return True
        
        # Consider expired if less than 5 minutes remaining
        return datetime.now() >= self._session.expires_at - timedelta(minutes=5)
    
    def get_auth_header(self) -> dict[str, str]:
        """Get authorization header for API requests."""
        if not self._session:
            return {}
        return {"Authorization": f"Bearer {self._session.access_token}"}

"""
Key management for X25519 keypairs.

Handles generation, storage, and loading of cryptographic keys.
Private keys are encrypted with AES-256-GCM using a passphrase-derived key.
"""

import os
import json
import base64
from pathlib import Path
from typing import Optional

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .passphrase import PassphraseDeriver


class KeyManager:
    """Manages X25519 keypairs with encrypted storage."""
    
    NONCE_LEN = 12  # 96 bits for AES-GCM
    
    def __init__(self, storage_dir: Path):
        """
        Initialize the key manager.
        
        Args:
            storage_dir: Directory for storing key files
        """
        self.storage_dir = storage_dir
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        
        self.public_key_path = storage_dir / "public_key.pem"
        self.private_key_path = storage_dir / "private_key.enc"
        
        # In-memory unlocked private key (cleared on logout/timeout)
        self._unlocked_private_key: Optional[X25519PrivateKey] = None
    
    @property
    def has_keys(self) -> bool:
        """Check if keys have been generated."""
        return self.public_key_path.exists() and self.private_key_path.exists()
    
    @property
    def is_unlocked(self) -> bool:
        """Check if the private key is currently unlocked in memory."""
        return self._unlocked_private_key is not None
    
    def generate_keypair(self, passphrase: str) -> tuple[bytes, bytes]:
        """
        Generate a new X25519 keypair and store encrypted.
        
        Args:
            passphrase: Passphrase to encrypt the private key
            
        Returns:
            Tuple of (public_key_pem, public_key_raw)
        """
        # Generate keypair
        private_key = X25519PrivateKey.generate()
        public_key = private_key.public_key()
        
        # Serialize public key
        public_key_pem = public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        )
        public_key_raw = public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw
        )
        
        # Serialize private key (raw bytes)
        private_key_raw = private_key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption()
        )
        
        # Derive encryption key from passphrase
        derived_key, salt = PassphraseDeriver.derive_key(passphrase)
        
        # Encrypt private key with AES-256-GCM
        nonce = os.urandom(self.NONCE_LEN)
        aesgcm = AESGCM(derived_key)
        ciphertext = aesgcm.encrypt(nonce, private_key_raw, None)
        
        # Store encrypted private key as JSON
        encrypted_data = {
            "salt": base64.b64encode(salt).decode("ascii"),
            "nonce": base64.b64encode(nonce).decode("ascii"),
            "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
            "algorithm": "X25519",
            "kdf": "argon2id"
        }
        
        # Write files
        self.public_key_path.write_bytes(public_key_pem)
        self.private_key_path.write_text(json.dumps(encrypted_data, indent=2))
        
        # Keep unlocked in memory
        self._unlocked_private_key = private_key
        
        return public_key_pem, public_key_raw
    
    def unlock(self, passphrase: str) -> bool:
        """
        Unlock the private key using the passphrase.
        
        Args:
            passphrase: The passphrase to decrypt the private key
            
        Returns:
            True if successful, False otherwise
        """
        if not self.has_keys:
            raise ValueError("No keys found. Generate keys first.")
        
        try:
            # Load encrypted data
            encrypted_data = json.loads(self.private_key_path.read_text())
            
            salt = base64.b64decode(encrypted_data["salt"])
            nonce = base64.b64decode(encrypted_data["nonce"])
            ciphertext = base64.b64decode(encrypted_data["ciphertext"])
            
            # Derive key from passphrase
            derived_key, _ = PassphraseDeriver.derive_key(passphrase, salt)
            
            # Decrypt private key
            aesgcm = AESGCM(derived_key)
            private_key_raw = aesgcm.decrypt(nonce, ciphertext, None)
            
            # Reconstruct private key object
            self._unlocked_private_key = X25519PrivateKey.from_private_bytes(private_key_raw)
            
            return True
            
        except Exception:
            return False
    
    def lock(self) -> None:
        """Lock the private key (clear from memory)."""
        self._unlocked_private_key = None
    
    def get_stored_salt(self) -> Optional[bytes]:
        """
        Get the salt stored with the encrypted private key.
        This is needed to derive the same key for vault encryption.
        
        Returns:
            The salt bytes, or None if no keys exist
        """
        if not self.private_key_path.exists():
            return None
        
        try:
            encrypted_data = json.loads(self.private_key_path.read_text())
            return base64.b64decode(encrypted_data["salt"])
        except Exception:
            return None
    
    def get_public_key(self) -> Optional[X25519PublicKey]:
        """Get the public key."""
        if not self.public_key_path.exists():
            return None
        
        public_key_pem = self.public_key_path.read_bytes()
        return serialization.load_pem_public_key(public_key_pem)
    
    def get_public_key_pem(self) -> Optional[bytes]:
        """Get the public key in PEM format."""
        if not self.public_key_path.exists():
            return None
        return self.public_key_path.read_bytes()
    
    def get_public_key_raw(self) -> Optional[bytes]:
        """Get the public key as raw bytes."""
        public_key = self.get_public_key()
        if public_key is None:
            return None
        return public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw
        )
    
    def get_unlocked_private_key(self) -> Optional[X25519PrivateKey]:
        """Get the unlocked private key (only if unlocked)."""
        return self._unlocked_private_key
    
    def perform_key_exchange(self, peer_public_key: X25519PublicKey) -> bytes:
        """
        Perform X25519 key exchange with a peer's public key.
        
        Args:
            peer_public_key: The peer's public key
            
        Returns:
            The shared secret
        """
        if not self.is_unlocked:
            raise ValueError("Private key must be unlocked first.")
        
        return self._unlocked_private_key.exchange(peer_public_key)

"""
Hoeilaart Practice Mapping Vault

Handles the import and storage of the Hoeilaart practice's pseudonymisation mapping.
The mapping file (mapping_encrypted.bin) is encrypted with AES-256-GCM using a practice password.

Flow:
1. User uploads mapping_encrypted.bin and provides the practice password
2. File is decrypted and validated
3. User creates a personal passphrase
4. Mapping is re-encrypted with the user's passphrase and stored locally
5. On subsequent logins, user unlocks with their passphrase
"""

import os
import json
import hashlib
import base64
from pathlib import Path
from typing import Any
from io import StringIO

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class HoeilaartVault:
    """Manages the Hoeilaart practice mapping vault."""
    
    NONCE_LEN = 12
    
    def __init__(self, mapping_path: Path, setup_flag_path: Path):
        """
        Initialize the Hoeilaart vault.
        
        Args:
            mapping_path: Path to store the encrypted mapping
            setup_flag_path: Path to the setup completion flag
        """
        self.mapping_path = mapping_path
        self.setup_flag_path = setup_flag_path
        self._cached_mappings: dict[str, dict] | None = None
    
    @property
    def is_setup_complete(self) -> bool:
        """Check if the Hoeilaart mapping has been set up."""
        return self.setup_flag_path.exists() and self.mapping_path.exists()
    
    def decrypt_original_file(self, encrypted_data: bytes, password: str) -> list[dict]:
        """
        Decrypt the original mapping_encrypted.bin file from the Hoeilaart pseudonymisation tool.
        
        The original file format is: salt (16 bytes) + nonce (12 bytes) + ciphertext
        Uses PBKDF2 for key derivation.
        
        Args:
            encrypted_data: The raw bytes from mapping_encrypted.bin
            password: The practice password used during pseudonymisation
            
        Returns:
            List of mapping records with keys: pseudoniem, origineel_id, naam, voornaam, email
            
        Raises:
            ValueError: If decryption fails (wrong password or corrupted file)
        """
        try:
            # Extract components (same format as pseudonymize.py)
            salt = encrypted_data[:16]
            nonce = encrypted_data[16:28]
            ciphertext = encrypted_data[28:]
            
            # Derive key using PBKDF2 (same as pseudonymize.py)
            key = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, 100000, dklen=32)
            
            # Decrypt
            aesgcm = AESGCM(key)
            plaintext = aesgcm.decrypt(nonce, ciphertext, None)
            
            # Parse JSON
            mapping_json = plaintext.decode('utf-8')
            records = json.loads(mapping_json)
            
            return records
            
        except Exception as e:
            raise ValueError(f"Decryption failed: {e}. Check if the password is correct.")
    
    def _derive_key(self, passphrase: str, salt: bytes | None = None) -> tuple[bytes, bytes]:
        """
        Derive an encryption key from a passphrase.
        
        Args:
            passphrase: User's passphrase
            salt: Optional salt (generated if not provided)
            
        Returns:
            Tuple of (derived_key, salt)
        """
        if salt is None:
            salt = os.urandom(16)
        key = hashlib.pbkdf2_hmac('sha256', passphrase.encode(), salt, 100000, dklen=32)
        return key, salt
    
    def setup(self, records: list[dict], passphrase: str) -> None:
        """
        Set up the Hoeilaart mapping vault with decrypted records.
        
        Converts the records to an indexed format and encrypts with the user's passphrase.
        
        Args:
            records: List of mapping records from decrypt_original_file
            passphrase: User's chosen passphrase for local encryption
        """
        # Convert to indexed format: pseudoniem -> {origineel_id, naam, voornaam, email}
        indexed_mapping = {}
        for record in records:
            pseudo_id = record.get("pseudoniem")
            if pseudo_id:
                indexed_mapping[pseudo_id] = {
                    "insz": record.get("origineel_id", ""),
                    "familienaam": record.get("naam", ""),
                    "voornaam": record.get("voornaam", ""),
                    "email": record.get("email", ""),
                }
        
        # Encrypt and save
        self._save_encrypted(indexed_mapping, passphrase)
        
        # Create setup flag
        self.setup_flag_path.write_text(json.dumps({
            "setup_complete": True,
            "patient_count": len(indexed_mapping),
        }))
        
        # Cache in memory
        self._cached_mappings = indexed_mapping
    
    def _save_encrypted(self, mapping: dict, passphrase: str) -> None:
        """Save mapping encrypted with passphrase."""
        key, salt = self._derive_key(passphrase)
        
        plaintext = json.dumps(mapping, ensure_ascii=False).encode('utf-8')
        nonce = os.urandom(self.NONCE_LEN)
        aesgcm = AESGCM(key)
        ciphertext = aesgcm.encrypt(nonce, plaintext, None)
        
        # Store as: salt (16) + nonce (12) + ciphertext
        encrypted_data = salt + nonce + ciphertext
        
        self.mapping_path.write_bytes(encrypted_data)
    
    def unlock(self, passphrase: str) -> bool:
        """
        Unlock the vault with the user's passphrase.
        
        Args:
            passphrase: User's passphrase
            
        Returns:
            True if unlock successful, False otherwise
        """
        if not self.mapping_path.exists():
            return False
        
        try:
            encrypted_data = self.mapping_path.read_bytes()
            
            # Extract components
            salt = encrypted_data[:16]
            nonce = encrypted_data[16:28]
            ciphertext = encrypted_data[28:]
            
            # Derive key
            key, _ = self._derive_key(passphrase, salt)
            
            # Decrypt
            aesgcm = AESGCM(key)
            plaintext = aesgcm.decrypt(nonce, ciphertext, None)
            
            # Parse and cache
            self._cached_mappings = json.loads(plaintext.decode('utf-8'))
            return True
            
        except Exception:
            self._cached_mappings = None
            return False
    
    def lock(self) -> None:
        """Lock the vault (clear cached mappings from memory)."""
        self._cached_mappings = None
    
    @property
    def is_unlocked(self) -> bool:
        """Check if the vault is currently unlocked."""
        return self._cached_mappings is not None
    
    @property
    def mapping_count(self) -> int:
        """Get the number of mappings in the vault."""
        if self._cached_mappings:
            return len(self._cached_mappings)
        return 0
    
    def resolve(self, pseudo_id: str) -> dict | None:
        """
        Resolve a pseudonym ID to real patient data.
        
        Args:
            pseudo_id: The pseudonymised patient ID (e.g., PSE-XXXX)
            
        Returns:
            Dict with keys: insz, familienaam, voornaam, email
            Or None if not found or vault is locked
        """
        if not self._cached_mappings:
            return None
        return self._cached_mappings.get(pseudo_id)
    
    def resolve_batch(self, pseudo_ids: list[str]) -> dict[str, dict]:
        """
        Resolve multiple pseudonym IDs at once.
        
        Args:
            pseudo_ids: List of pseudonymised patient IDs
            
        Returns:
            Dict mapping pseudo_id -> patient data for found entries
        """
        if not self._cached_mappings:
            return {}
        
        results = {}
        for pid in pseudo_ids:
            if pid in self._cached_mappings:
                results[pid] = self._cached_mappings[pid]
        return results
    
    def get_all_mappings(self) -> dict[str, dict]:
        """
        Get all mappings (for bulk operations).
        
        Returns:
            Copy of all mappings or empty dict if locked
        """
        if not self._cached_mappings:
            return {}
        return dict(self._cached_mappings)
    
    def clear(self) -> None:
        """Clear the vault completely (remove all stored data)."""
        self._cached_mappings = None
        if self.mapping_path.exists():
            self.mapping_path.unlink()
        if self.setup_flag_path.exists():
            self.setup_flag_path.unlink()

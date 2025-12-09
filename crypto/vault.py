"""
Vault encryption for patient identity mappings.

Uses AES-256-GCM with a random DEK (Data Encryption Key).
The DEK is wrapped using X25519 key exchange + AES-KW.
"""

import os
import json
import base64
from typing import Any
from dataclasses import dataclass

from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.keywrap import aes_key_wrap, aes_key_unwrap


@dataclass
class EncryptedVault:
    """Represents an encrypted vault ready for cloud upload."""
    ciphertext: bytes
    nonce: bytes
    wrapped_dek: bytes
    ephemeral_public_key: bytes
    metadata: dict[str, Any]
    
    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dictionary."""
        return {
            "ciphertext": base64.b64encode(self.ciphertext).decode("ascii"),
            "nonce": base64.b64encode(self.nonce).decode("ascii"),
            "wrapped_dek": base64.b64encode(self.wrapped_dek).decode("ascii"),
            "ephemeral_public_key": base64.b64encode(self.ephemeral_public_key).decode("ascii"),
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EncryptedVault":
        """Reconstruct from dictionary."""
        return cls(
            ciphertext=base64.b64decode(data["ciphertext"]),
            nonce=base64.b64decode(data["nonce"]),
            wrapped_dek=base64.b64decode(data["wrapped_dek"]),
            ephemeral_public_key=base64.b64decode(data["ephemeral_public_key"]),
            metadata=data.get("metadata", {}),
        )


class VaultEncryptor:
    """Encrypts and decrypts patient identity mapping vaults."""
    
    DEK_LEN = 32  # 256 bits
    NONCE_LEN = 12  # 96 bits for AES-GCM
    HKDF_INFO = b"cerebro-vault-dek-wrap"
    
    @classmethod
    def encrypt_mapping(
        cls,
        mapping: dict[str, Any],
        recipient_public_key: X25519PublicKey,
        metadata: dict[str, Any] | None = None
    ) -> EncryptedVault:
        """
        Encrypt a patient identity mapping for secure cloud storage.
        
        The mapping is encrypted with AES-256-GCM using a random DEK.
        The DEK is wrapped using X25519 ECDH + HKDF + AES-KW.
        
        Args:
            mapping: Dictionary mapping PIDs to patient identities
            recipient_public_key: The doctor's public key
            metadata: Optional metadata to include (not encrypted)
            
        Returns:
            EncryptedVault ready for cloud upload
        """
        # Generate random DEK
        dek = os.urandom(cls.DEK_LEN)
        
        # Encrypt mapping with DEK
        plaintext = json.dumps(mapping, ensure_ascii=False).encode("utf-8")
        nonce = os.urandom(cls.NONCE_LEN)
        aesgcm = AESGCM(dek)
        ciphertext = aesgcm.encrypt(nonce, plaintext, None)
        
        # Wrap DEK using X25519 + HKDF + AES-KW
        # Generate ephemeral keypair for this encryption
        ephemeral_private = X25519PrivateKey.generate()
        ephemeral_public = ephemeral_private.public_key()
        
        # Perform key exchange
        shared_secret = ephemeral_private.exchange(recipient_public_key)
        
        # Derive wrapping key from shared secret
        wrapping_key = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=None,
            info=cls.HKDF_INFO,
        ).derive(shared_secret)
        
        # Wrap the DEK
        wrapped_dek = aes_key_wrap(wrapping_key, dek)
        
        # Get ephemeral public key bytes
        ephemeral_public_bytes = ephemeral_public.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw
        )
        
        return EncryptedVault(
            ciphertext=ciphertext,
            nonce=nonce,
            wrapped_dek=wrapped_dek,
            ephemeral_public_key=ephemeral_public_bytes,
            metadata=metadata or {},
        )
    
    @classmethod
    def decrypt_mapping(
        cls,
        vault: EncryptedVault,
        private_key: X25519PrivateKey
    ) -> dict[str, Any]:
        """
        Decrypt a patient identity mapping vault.
        
        Args:
            vault: The encrypted vault
            private_key: The doctor's private key (must be unlocked)
            
        Returns:
            The decrypted mapping dictionary
        """
        # Reconstruct ephemeral public key
        ephemeral_public = X25519PublicKey.from_public_bytes(vault.ephemeral_public_key)
        
        # Perform key exchange
        shared_secret = private_key.exchange(ephemeral_public)
        
        # Derive wrapping key
        wrapping_key = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=None,
            info=cls.HKDF_INFO,
        ).derive(shared_secret)
        
        # Unwrap DEK
        dek = aes_key_unwrap(wrapping_key, vault.wrapped_dek)
        
        # Decrypt mapping
        aesgcm = AESGCM(dek)
        plaintext = aesgcm.decrypt(vault.nonce, vault.ciphertext, None)
        
        return json.loads(plaintext.decode("utf-8"))


class LocalVaultCache:
    """Manages local encrypted cache of mapping vault."""
    
    NONCE_LEN = 12
    
    def __init__(self, cache_path):
        """
        Initialize the local vault cache.
        
        Args:
            cache_path: Path to the cache file
        """
        self.cache_path = cache_path
    
    def save(self, mapping: dict[str, Any], encryption_key: bytes) -> None:
        """
        Save mapping to local encrypted cache.
        
        Args:
            mapping: The mapping to cache
            encryption_key: AES-256 key for encryption
        """
        plaintext = json.dumps(mapping, ensure_ascii=False).encode("utf-8")
        nonce = os.urandom(self.NONCE_LEN)
        aesgcm = AESGCM(encryption_key)
        ciphertext = aesgcm.encrypt(nonce, plaintext, None)
        
        cache_data = {
            "nonce": base64.b64encode(nonce).decode("ascii"),
            "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
        }
        
        self.cache_path.write_text(json.dumps(cache_data))
    
    def load(self, encryption_key: bytes) -> dict[str, Any] | None:
        """
        Load mapping from local encrypted cache.
        
        Args:
            encryption_key: AES-256 key for decryption
            
        Returns:
            The decrypted mapping or None if not found/invalid
        """
        if not self.cache_path.exists():
            return None
        
        try:
            cache_data = json.loads(self.cache_path.read_text())
            nonce = base64.b64decode(cache_data["nonce"])
            ciphertext = base64.b64decode(cache_data["ciphertext"])
            
            aesgcm = AESGCM(encryption_key)
            plaintext = aesgcm.decrypt(nonce, ciphertext, None)
            
            return json.loads(plaintext.decode("utf-8"))
        except Exception:
            return None
    
    def clear(self) -> None:
        """Clear the local cache."""
        if self.cache_path.exists():
            self.cache_path.unlink()

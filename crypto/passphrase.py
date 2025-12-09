"""
Passphrase derivation using Argon2id.

The passphrase is used to derive a symmetric key for encrypting the private key.
"""

import os
import base64
from argon2.low_level import hash_secret_raw, Type


class PassphraseDeriver:
    """Derives encryption keys from passphrases using Argon2id."""
    
    # Argon2id parameters (OWASP recommended)
    TIME_COST = 3  # iterations
    MEMORY_COST = 65536  # 64 MB
    PARALLELISM = 4
    HASH_LEN = 32  # 256 bits for AES-256
    SALT_LEN = 16  # 128 bits
    
    @classmethod
    def derive_key(cls, passphrase: str, salt: bytes | None = None) -> tuple[bytes, bytes]:
        """
        Derive a 256-bit key from a passphrase using Argon2id.
        
        Args:
            passphrase: The user's passphrase
            salt: Optional salt bytes. If None, generates a random salt.
            
        Returns:
            Tuple of (derived_key, salt)
        """
        if salt is None:
            salt = os.urandom(cls.SALT_LEN)
        
        derived_key = hash_secret_raw(
            secret=passphrase.encode("utf-8"),
            salt=salt,
            time_cost=cls.TIME_COST,
            memory_cost=cls.MEMORY_COST,
            parallelism=cls.PARALLELISM,
            hash_len=cls.HASH_LEN,
            type=Type.ID,  # Argon2id
        )
        
        return derived_key, salt
    
    @classmethod
    def derive_key_with_stored_salt(cls, passphrase: str, salt_b64: str) -> bytes:
        """
        Derive a key using a previously stored salt (base64 encoded).
        
        Args:
            passphrase: The user's passphrase
            salt_b64: Base64-encoded salt from previous derivation
            
        Returns:
            The derived key
        """
        salt = base64.b64decode(salt_b64)
        derived_key, _ = cls.derive_key(passphrase, salt)
        return derived_key

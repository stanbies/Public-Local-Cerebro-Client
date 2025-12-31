"""
Cryptographic module for Cerebro Companion Client.

Handles:
- Key generation (X25519 keypairs)
- Passphrase derivation (Argon2id)
- Vault encryption (AES-256-GCM)
- DEK wrapping
"""

from .key_manager import KeyManager
from .vault import VaultEncryptor
from .passphrase import PassphraseDeriver
from .hoeilaart_vault import HoeilaartVault

__all__ = ["KeyManager", "VaultEncryptor", "PassphraseDeriver", "HoeilaartVault"]

"""
Configuration for Cerebro Companion Client.
"""

import os
from pathlib import Path
from dataclasses import dataclass

# Application version - update this for each release
VERSION = "1.0.2"


@dataclass
class Config:
    """Application configuration."""
    
    # Server settings
    HOST: str = "127.0.0.1"
    PORT: int = 18421
    
    # Cloud API settings - Default to Render.com hosted backend
    CLOUD_API_URL: str = os.getenv("CEREBRO_CLOUD_URL", "https://pilot-cerebro.onrender.com")
    
    # Storage paths (will be set to AppData on Windows for production)
    STORAGE_DIR: Path = Path(__file__).parent / "data"
    
    # Cryptographic settings
    PSEUDONYMISATION_SALT: str = os.getenv("CEREBRO_SALT", "cerebro_local_default_salt_2024")
    
    # Session settings
    SESSION_TIMEOUT_MINUTES: int = 30
    
    def __post_init__(self):
        """Ensure storage directory exists."""
        self.STORAGE_DIR.mkdir(parents=True, exist_ok=True)
    
    @property
    def keys_dir(self) -> Path:
        """Directory for cryptographic keys."""
        path = self.STORAGE_DIR / "keys"
        path.mkdir(parents=True, exist_ok=True)
        return path
    
    @property
    def cache_dir(self) -> Path:
        """Directory for cached data."""
        path = self.STORAGE_DIR / "cache"
        path.mkdir(parents=True, exist_ok=True)
        return path
    
    @property
    def logs_dir(self) -> Path:
        """Directory for log files."""
        path = self.STORAGE_DIR / "logs"
        path.mkdir(parents=True, exist_ok=True)
        return path
    
    @property
    def jwt_path(self) -> Path:
        """Path to encrypted JWT storage."""
        return self.cache_dir / "jwt.enc"
    
    @property
    def mapping_cache_path(self) -> Path:
        """Path to encrypted mapping cache."""
        return self.cache_dir / "mapping_cache.enc"
    
    @property
    def practice_config_path(self) -> Path:
        """Path to practice configuration."""
        return self.STORAGE_DIR / "practice_config.json"
    
    @property
    def hoeilaart_mapping_path(self) -> Path:
        """Path to encrypted Hoeilaart mapping cache (separate from regular mappings)."""
        return self.cache_dir / "hoeilaart_mapping.enc"
    
    @property
    def hoeilaart_setup_flag_path(self) -> Path:
        """Path to flag file indicating Hoeilaart mapping has been set up."""
        return self.cache_dir / "hoeilaart_setup.flag"


# Global config instance
config = Config()

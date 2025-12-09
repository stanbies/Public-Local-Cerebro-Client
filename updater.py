"""
Auto-update module for Cerebro Companion.

Checks for new versions using GitHub API (for public repos) or version file (Docker).
"""

import os
import asyncio
import subprocess
import logging
from pathlib import Path
from typing import Optional
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

# GitHub repository info
GITHUB_OWNER = "stanbies"
GITHUB_REPO = "Cerebro-Local-Client"
GITHUB_API_URL = f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}"

# Version file path (updated by start.bat before Docker starts)
VERSION_FILE = Path("/app/data/.latest_version")


@dataclass
class UpdateInfo:
    """Information about an available update."""
    current_version: str
    latest_version: str
    update_available: bool
    release_notes: str = ""
    release_url: str = ""
    published_at: str = ""
    has_new_commits: bool = False


class UpdateChecker:
    """Checks for updates using git commands or version file."""
    
    def __init__(self, current_version: str):
        self.current_version = current_version
        self._latest_info: Optional[UpdateInfo] = None
        self._check_in_progress = False
        self._is_docker = is_running_in_docker()
    
    def _parse_version(self, version_str: str) -> tuple:
        """Parse version string to comparable tuple."""
        # Remove 'v' prefix if present
        clean = version_str.lstrip('v').strip()
        try:
            parts = clean.split('.')
            return tuple(int(p) for p in parts)
        except (ValueError, AttributeError):
            return (0, 0, 0)
    
    def _is_newer_version(self, latest: str, current: str) -> bool:
        """Check if latest version is newer than current."""
        latest_tuple = self._parse_version(latest)
        current_tuple = self._parse_version(current)
        return latest_tuple > current_tuple
    
    def _run_git_command(self, args: list[str]) -> Optional[str]:
        """Run a git command and return output."""
        try:
            result = subprocess.run(
                ["git"] + args,
                capture_output=True,
                text=True,
                timeout=30,
                cwd=os.path.dirname(os.path.abspath(__file__))
            )
            if result.returncode == 0:
                return result.stdout.strip()
            logger.warning(f"Git command failed: {result.stderr}")
            return None
        except subprocess.TimeoutExpired:
            logger.warning("Git command timed out")
            return None
        except Exception as e:
            logger.warning(f"Git command error: {e}")
            return None
    
    def _check_version_file(self) -> Optional[UpdateInfo]:
        """Check version file (used in Docker)."""
        try:
            if VERSION_FILE.exists():
                content = VERSION_FILE.read_text().strip()
                lines = content.split('\n')
                latest_version = lines[0].lstrip('v') if lines else ""
                has_new_commits = len(lines) > 1 and lines[1] == "has_commits"
                
                if latest_version:
                    update_available = self._is_newer_version(latest_version, self.current_version)
                    if has_new_commits and not update_available:
                        update_available = True
                    
                    return UpdateInfo(
                        current_version=self.current_version,
                        latest_version=latest_version,
                        update_available=update_available,
                        release_url=f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}",
                        has_new_commits=has_new_commits
                    )
        except Exception as e:
            logger.warning(f"Error reading version file: {e}")
        return None
    
    async def _check_github_api(self) -> Optional[UpdateInfo]:
        """Check GitHub API for latest release/tag (works for public repos)."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                # Try to get latest release first
                response = await client.get(
                    f"{GITHUB_API_URL}/releases/latest",
                    headers={"Accept": "application/vnd.github.v3+json"}
                )
                
                if response.status_code == 200:
                    data = response.json()
                    latest_version = data.get("tag_name", "").lstrip('v')
                    
                    return UpdateInfo(
                        current_version=self.current_version,
                        latest_version=latest_version,
                        update_available=self._is_newer_version(latest_version, self.current_version),
                        release_notes=data.get("body", ""),
                        release_url=data.get("html_url", ""),
                        published_at=data.get("published_at", "")
                    )
                
                # Fallback: check tags if no releases
                response = await client.get(
                    f"{GITHUB_API_URL}/tags",
                    headers={"Accept": "application/vnd.github.v3+json"}
                )
                
                if response.status_code == 200:
                    tags = response.json()
                    if tags:
                        latest_tag = tags[0].get("name", "").lstrip('v')
                        return UpdateInfo(
                            current_version=self.current_version,
                            latest_version=latest_tag,
                            update_available=self._is_newer_version(latest_tag, self.current_version),
                            release_url=f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases/tag/{tags[0].get('name', '')}"
                        )
                
        except httpx.TimeoutException:
            logger.warning("Timeout checking GitHub API for updates")
        except httpx.RequestError as e:
            logger.warning(f"Error checking GitHub API: {e}")
        except Exception as e:
            logger.warning(f"Unexpected error checking GitHub API: {e}")
        return None
    
    async def check_for_updates(self) -> UpdateInfo:
        """Check for updates using GitHub API, version file, or git commands."""
        if self._check_in_progress:
            if self._latest_info:
                return self._latest_info
            return UpdateInfo(
                current_version=self.current_version,
                latest_version=self.current_version,
                update_available=False
            )
        
        self._check_in_progress = True
        
        try:
            # Try GitHub API first (works for public repos)
            info = await self._check_github_api()
            if info:
                self._latest_info = info
                return info
            
            # In Docker, check version file as fallback
            if self._is_docker:
                info = self._check_version_file()
                if info:
                    self._latest_info = info
                    return info
                # No version file, return no update
                self._latest_info = UpdateInfo(
                    current_version=self.current_version,
                    latest_version=self.current_version,
                    update_available=False
                )
                return self._latest_info
            
            # Outside Docker, use git commands as fallback
            loop = asyncio.get_event_loop()
            
            # Fetch latest from remote
            await loop.run_in_executor(None, self._run_git_command, ["fetch", "origin", "main"])
            
            # Get local and remote commit hashes
            local_hash = await loop.run_in_executor(None, self._run_git_command, ["rev-parse", "HEAD"])
            remote_hash = await loop.run_in_executor(None, self._run_git_command, ["rev-parse", "origin/main"])
            
            has_new_commits = local_hash != remote_hash if (local_hash and remote_hash) else False
            
            # Get latest tag from remote
            await loop.run_in_executor(None, self._run_git_command, ["fetch", "--tags"])
            tags_output = await loop.run_in_executor(
                None, self._run_git_command, 
                ["tag", "--sort=-version:refname"]
            )
            
            latest_tag = ""
            if tags_output:
                tags = tags_output.split('\n')
                # Find first tag that looks like a version
                for tag in tags:
                    tag = tag.strip()
                    if tag and (tag.startswith('v') or tag[0].isdigit()):
                        latest_tag = tag.lstrip('v')
                        break
            
            # Determine if update is available
            update_available = False
            latest_version = self.current_version
            
            if latest_tag:
                latest_version = latest_tag
                update_available = self._is_newer_version(latest_tag, self.current_version)
            
            # Also consider new commits as an update
            if has_new_commits and not update_available:
                update_available = True
                if not latest_tag:
                    latest_version = "new commits"
            
            self._latest_info = UpdateInfo(
                current_version=self.current_version,
                latest_version=latest_version,
                update_available=update_available,
                release_url=f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}",
                has_new_commits=has_new_commits
            )
            return self._latest_info
                
        except Exception as e:
            logger.error(f"Unexpected error checking for updates: {e}")
        finally:
            self._check_in_progress = False
        
        # Return no update on error
        return UpdateInfo(
            current_version=self.current_version,
            latest_version=self.current_version,
            update_available=False
        )
    
    def get_cached_info(self) -> Optional[UpdateInfo]:
        """Get cached update info without making a request."""
        return self._latest_info


def is_running_in_docker() -> bool:
    """Check if running inside a Docker container."""
    return os.path.exists('/.dockerenv') or os.environ.get('DOCKER_CONTAINER', False)


def get_update_command() -> str:
    """
    Get the command to run for updating.
    In Docker, this means pulling the latest image and restarting.
    """
    if is_running_in_docker():
        return "docker-compose pull && docker-compose up -d"
    return "git pull && pip install -r requirements.txt"

"""
Cloud upload functionality for Cerebro Companion Client.

Handles secure upload of:
- Anonymised patient profiles
- Care tasks
- Encrypted mapping vaults
"""

import httpx
from typing import Any, Optional
from dataclasses import dataclass


@dataclass
class UploadResult:
    """Result of a cloud upload operation."""
    success: bool
    message: str
    patient_ids: list[str] = None
    errors: list[str] = None
    
    def __post_init__(self):
        if self.patient_ids is None:
            self.patient_ids = []
        if self.errors is None:
            self.errors = []


class CloudUploader:
    """Handles uploads to the Cerebro cloud API."""
    
    def __init__(self, api_base_url: str, jwt_token: str):
        """
        Initialize the cloud uploader.
        
        Args:
            api_base_url: Base URL of the Cerebro cloud API
            jwt_token: JWT authentication token
        """
        self.api_base_url = api_base_url.rstrip("/")
        self.jwt_token = jwt_token
        self._client: Optional[httpx.AsyncClient] = None
    
    def _get_headers(self) -> dict[str, str]:
        """Get headers for API requests."""
        return {
            "Authorization": f"Bearer {self.jwt_token}",
            "Content-Type": "application/json",
        }
    
    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create async HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client
    
    async def close(self):
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None
    
    async def upload_patients(
        self,
        profiles: list[dict[str, Any]],
        care_tasks: list[dict[str, Any]]
    ) -> UploadResult:
        """
        Upload anonymised patient profiles and care tasks to the cloud.
        
        Args:
            profiles: List of anonymised patient profile dictionaries
            care_tasks: List of care task dictionaries
            
        Returns:
            UploadResult with status and any errors
        """
        client = await self._get_client()
        result = UploadResult(success=False, message="")
        
        if not profiles:
            result.message = "No profiles to upload"
            return result
        
        try:
            # Build patients payload for batch upload
            patients_payload = []
            
            for profile in profiles:
                # Get pseudo_id from profile
                patient_info = profile.get("patient_info", {})
                pseudo_id = patient_info.get("id") or patient_info.get("pseudo_id", "unknown")
                
                # Get tasks for this patient
                patient_tasks = [
                    t for t in care_tasks 
                    if t.get("patient_id") == pseudo_id
                ]
                
                # Build overview from profile (simplified)
                overview = {
                    "pseudo_id": pseudo_id,
                    "conditions_count": len(profile.get("conditions", [])),
                    "medications_count": len(profile.get("medications", [])),
                    "source_files": [],
                }
                
                patients_payload.append({
                    "pseudo_id": pseudo_id,
                    "profile": profile,
                    "overview": overview,
                    "care_tasks": patient_tasks,
                })
            
            # Send batch request to the local client upload endpoint
            url = f"{self.api_base_url}/api/patients/upload/local/"
            print(f"[UPLOAD] Sending {len(patients_payload)} patient(s) to {url}")
            
            response = await client.post(
                url,
                headers=self._get_headers(),
                json={"patients": patients_payload},
            )
            
            print(f"[UPLOAD] Response status: {response.status_code}")
            
            if response.status_code in (200, 201):
                response_data = response.json()
                print(f"[UPLOAD] Response: {response_data}")
                
                result.success = response_data.get("success", True)
                result.message = response_data.get("message", f"Uploaded {len(patients_payload)} patient(s)")
                
                # Extract patient IDs from response
                for processed in response_data.get("processed", []):
                    result.patient_ids.append(processed.get("pseudo_id", "unknown"))
                
                # Collect any errors
                for error in response_data.get("errors", []):
                    if isinstance(error, dict):
                        result.errors.append(f"{error.get('pseudo_id', 'unknown')}: {error.get('error', 'Unknown error')}")
                    else:
                        result.errors.append(str(error))
            else:
                error_msg = f"Failed to upload patients: {response.status_code}"
                try:
                    error_data = response.json()
                    print(f"[UPLOAD] Error response: {error_data}")
                    error_msg += f" - {error_data.get('error', error_data.get('detail', ''))}"
                except Exception:
                    print(f"[UPLOAD] Error response text: {response.text}")
                result.errors.append(error_msg)
                result.message = error_msg
                
        except httpx.RequestError as e:
            print(f"[UPLOAD] Network error: {e}")
            result.errors.append(f"Network error: {str(e)}")
            result.message = "Network error during upload"
        except Exception as e:
            print(f"[UPLOAD] Unexpected error: {e}")
            result.errors.append(f"Unexpected error: {str(e)}")
            result.message = "Unexpected error during upload"
        
        return result
    
    async def upload_mapping_vault(self, encrypted_vault: dict[str, Any]) -> UploadResult:
        """
        Upload an encrypted mapping vault.
        
        Args:
            encrypted_vault: The encrypted vault dictionary
            
        Returns:
            UploadResult with status
        """
        client = await self._get_client()
        result = UploadResult(success=False, message="")
        
        try:
            response = await client.post(
                f"{self.api_base_url}/api/mapping-vault/",
                headers=self._get_headers(),
                json=encrypted_vault,
            )
            
            if response.status_code in (200, 201):
                result.success = True
                result.message = "Mapping vault uploaded successfully"
            else:
                error_msg = f"Failed to upload vault: {response.status_code}"
                try:
                    error_data = response.json()
                    error_msg += f" - {error_data.get('detail', '')}"
                except Exception:
                    pass
                result.errors.append(error_msg)
                result.message = error_msg
                
        except httpx.RequestError as e:
            result.errors.append(f"Network error: {str(e)}")
            result.message = "Network error during vault upload"
        except Exception as e:
            result.errors.append(f"Unexpected error: {str(e)}")
            result.message = "Unexpected error during vault upload"
        
        return result
    
    async def download_mapping_vault(self) -> tuple[Optional[dict[str, Any]], Optional[str]]:
        """
        Download the encrypted mapping vault from cloud.
        
        Returns:
            Tuple of (vault_data, error_message)
        """
        client = await self._get_client()
        
        try:
            response = await client.get(
                f"{self.api_base_url}/api/download-mapping-vault/",
                headers=self._get_headers(),
            )
            
            if response.status_code == 200:
                return response.json(), None
            elif response.status_code == 404:
                return None, "No mapping vault found"
            else:
                return None, f"Failed to download vault: {response.status_code}"
                
        except httpx.RequestError as e:
            return None, f"Network error: {str(e)}"
        except Exception as e:
            return None, f"Unexpected error: {str(e)}"
    
    async def register_public_key(self, public_key_pem: str) -> UploadResult:
        """
        Register the doctor's public key with the cloud.
        
        Args:
            public_key_pem: The public key in PEM format
            
        Returns:
            UploadResult with status
        """
        client = await self._get_client()
        result = UploadResult(success=False, message="")
        
        try:
            response = await client.post(
                f"{self.api_base_url}/api/register-public-key/",
                headers=self._get_headers(),
                json={"public_key": public_key_pem},
            )
            
            if response.status_code in (200, 201):
                result.success = True
                result.message = "Public key registered successfully"
            else:
                error_msg = f"Failed to register key: {response.status_code}"
                try:
                    error_data = response.json()
                    error_msg += f" - {error_data.get('detail', '')}"
                except Exception:
                    pass
                result.errors.append(error_msg)
                result.message = error_msg
                
        except httpx.RequestError as e:
            result.errors.append(f"Network error: {str(e)}")
            result.message = "Network error during key registration"
        except Exception as e:
            result.errors.append(f"Unexpected error: {str(e)}")
            result.message = "Unexpected error during key registration"
        
        return result

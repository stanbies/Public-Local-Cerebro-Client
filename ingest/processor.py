"""
XML processing and pseudonymisation using cerebro_care.

This module handles the full ingestion pipeline:
1. Parse XML files (SUMEHR/PMF)
2. Extract patient profiles
3. Anonymise and generate mappings
4. Prepare data for cloud upload
"""

import os
import tempfile
from pathlib import Path
from typing import Any, Callable, Optional
from dataclasses import dataclass, field
from datetime import datetime

from cerebro_care import (
    batch_process_and_anonymise,
    xml_to_patient_profile,
    anonymise_profile,
    profile_to_dict,
    profile_to_caretasks,
)


@dataclass
class ProcessingResult:
    """Result of processing XML files."""
    success: bool
    patient_count: int = 0
    profiles: list[dict[str, Any]] = field(default_factory=list)
    mappings: list[dict[str, Any]] = field(default_factory=list)
    care_tasks: list[dict[str, Any]] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    processing_time_ms: int = 0


@dataclass
class ProgressUpdate:
    """Progress update during processing."""
    stage: str
    message: str
    progress: float  # 0.0 to 1.0
    current_file: Optional[str] = None


class XMLProcessor:
    """Processes XML files and generates anonymised patient data."""
    
    def __init__(
        self,
        salt: str,
        progress_callback: Optional[Callable[[ProgressUpdate], None]] = None
    ):
        """
        Initialize the XML processor.
        
        Args:
            salt: Secret salt for consistent pseudo ID generation
            progress_callback: Optional callback for progress updates
        """
        self.salt = salt
        self.progress_callback = progress_callback
    
    def _report_progress(self, stage: str, message: str, progress: float, current_file: str = None):
        """Report progress to callback if set."""
        if self.progress_callback:
            self.progress_callback(ProgressUpdate(
                stage=stage,
                message=message,
                progress=progress,
                current_file=current_file
            ))
    
    def process_files(self, files: list[tuple[str, bytes]]) -> ProcessingResult:
        """
        Process multiple XML files.
        
        Args:
            files: List of (filename, content) tuples
            
        Returns:
            ProcessingResult with anonymised profiles and mappings
        """
        start_time = datetime.now()
        result = ProcessingResult(success=False)
        
        if not files:
            result.errors.append("No files provided")
            return result
        
        self._report_progress("reading", "Reading files...", 0.0)
        
        # Create temporary directory for processing
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            
            # Write files to temp directory
            xml_files = []
            for i, (filename, content) in enumerate(files):
                progress = (i + 1) / len(files) * 0.2  # 0-20% for file reading
                self._report_progress("reading", f"Reading {filename}...", progress, filename)
                
                # Validate extension
                ext = Path(filename).suffix.lower()
                if ext not in [".xml", ".pmf", ".sumehr"]:
                    result.errors.append(f"Invalid file type: {filename}")
                    continue
                
                file_path = temp_path / filename
                file_path.write_bytes(content)
                xml_files.append(file_path)
            
            if not xml_files:
                result.errors.append("No valid XML files found")
                return result
            
            self._report_progress("extracting", "Extracting structured fields...", 0.25)
            
            try:
                # Use batch_process_and_anonymise from cerebro_care
                output_dir = temp_path / "output"
                
                summary = batch_process_and_anonymise(
                    xml_dir=temp_path,
                    output_dir=output_dir,
                    pattern="*.xml",
                    salt=self.salt,
                    redacted_placeholder="[REDACTED]",
                    anonymise_care_team=True,
                    run_annotators=True,
                    group_by_patient=True,
                    save_profiles=True,
                    save_mappings=True,
                    verbose=False,
                )
                
                self._report_progress("generating", "Generating PIDs...", 0.5)
                
                # Load the generated profiles and mappings
                profiles_dir = output_dir / "profiles"
                mappings_dir = output_dir / "mappings"
                
                if profiles_dir.exists():
                    for profile_file in profiles_dir.glob("*.json"):
                        import json
                        profile_data = json.loads(profile_file.read_text(encoding="utf-8"))
                        result.profiles.append(profile_data)
                
                self._report_progress("generating", "Processing mappings...", 0.6)
                
                if mappings_dir.exists():
                    for mapping_file in mappings_dir.glob("*.json"):
                        import json
                        mapping_data = json.loads(mapping_file.read_text(encoding="utf-8"))
                        result.mappings.append(mapping_data)
                
                self._report_progress("tasks", "Generating care tasks...", 0.7)
                
                # Generate care tasks for each profile
                for profile_data in result.profiles:
                    try:
                        from cerebro_care import profile_from_dict
                        profile = profile_from_dict(profile_data)
                        tasks = profile_to_caretasks(profile)
                        
                        for task in tasks:
                            task_dict = {
                                "description": task.description,
                                "required_profession": task.required_profession,
                                "recommended_frequency": task.recommended_frequency,
                                "priority": task.priority,
                                "explanation": task.explanation,
                                "patient_id": task.patient_id,
                                "due_date": task.due_date.isoformat() if task.due_date else None,
                                "condition": task.condition,
                                "task_type": task.task_type,
                            }
                            result.care_tasks.append(task_dict)
                    except Exception as e:
                        result.errors.append(f"Error generating tasks: {str(e)}")
                
                result.patient_count = summary.get("patients_processed", len(result.profiles))
                result.errors.extend(summary.get("errors", []))
                result.success = result.patient_count > 0
                
                self._report_progress("complete", "Processing complete", 1.0)
                
            except Exception as e:
                result.errors.append(f"Processing error: {str(e)}")
                self._report_progress("error", f"Error: {str(e)}", 1.0)
        
        end_time = datetime.now()
        result.processing_time_ms = int((end_time - start_time).total_seconds() * 1000)
        
        return result
    
    def process_single_file(self, filename: str, content: bytes) -> ProcessingResult:
        """
        Process a single XML file.
        
        Args:
            filename: The filename
            content: The file content as bytes
            
        Returns:
            ProcessingResult with anonymised profile and mapping
        """
        return self.process_files([(filename, content)])


def create_mapping_for_vault(mappings: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """
    Create a combined mapping dictionary for vault encryption.
    
    Args:
        mappings: List of individual patient mappings
        
    Returns:
        Dictionary mapping PIDs to patient identity data
    """
    vault_mapping = {}
    
    for mapping in mappings:
        pseudo_id = mapping.get("pseudo_id")
        if pseudo_id:
            vault_mapping[pseudo_id] = {
                "original_id": mapping.get("original_id"),
                "first_name": mapping.get("first_name"),
                "last_name": mapping.get("last_name"),
                "birth_date": mapping.get("birth_date"),
                "insz": mapping.get("insz"),
                "address": mapping.get("address"),
                "phone": mapping.get("phone"),
                "emails": mapping.get("emails", []),
                "created_at": mapping.get("created_at"),
            }
    
    return vault_mapping

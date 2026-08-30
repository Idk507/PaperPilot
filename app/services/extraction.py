"""Document extraction service — pdfplumber/pytesseract wrapper.

Phase 0: placeholder returning empty dict.
Full implementation in Phase 5.

Security note: extracted text is NEVER echoed to the agent raw.
Only validated field values are returned. See SECURITY.md section 2.
"""

from __future__ import annotations

from pathlib import Path


def extract_fields(file_path: Path, document_type: str) -> dict[str, str]:
    """Extract grant-relevant fields from a PDF or image file.

    Returns a dict of {field_name: extracted_value}. Values that don't
    pass field-level validation are excluded (never returned raw).
    """
    return {}

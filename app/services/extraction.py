"""Document extraction service — pdfplumber / pytesseract pipeline.

Security model (SECURITY.md §2):
  - Raw OCR/PDF text is NEVER returned to an agent or stored in ToolCallLog.
  - Only validated field values (those that pass the same Pydantic-equivalent
    validators used for human input) leave this module.
  - Each extracted candidate is passed through _validate_candidate(); failures
    are silently dropped.
  - Prompt-injection phrases in extracted text are detected and the entire
    field candidate is discarded.

Extraction pipeline:
  1. If PDF → pdfplumber.  If image → pytesseract (fallback; degrades gracefully
     when tesseract binary is not installed).
  2. Full-page text is passed to regex extractors per field name.
  3. Each raw candidate is sanitised and validated before inclusion.
  4. Only the final {field_name: value} dict is returned — no raw text escapes.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

_log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompt-injection guard — discard any candidate that contains these patterns
# ---------------------------------------------------------------------------
_INJECTION_PATTERNS: list[re.Pattern] = [
    re.compile(r"ignore\s+(all\s+)?previous\s+instructions?", re.I),
    re.compile(r"disregard\s+(all\s+)?prior\s+instructions?", re.I),
    re.compile(r"you\s+are\s+(now|a)\s+", re.I),
    re.compile(r"<\s*/?(?:script|iframe|img|object|embed)", re.I),
    re.compile(r"\[SYSTEM\]|\[USER\]|\[ASSISTANT\]", re.I),
    re.compile(r"act\s+as\s+(if|a|an)\s+", re.I),
    re.compile(r"pretend\s+(you\s+are|to\s+be)\s+", re.I),
]


def _is_injection(text: str) -> bool:
    return any(p.search(text) for p in _INJECTION_PATTERNS)


# ---------------------------------------------------------------------------
# Field-level validators — same rules as _validate_proposed_field in form.py
# ---------------------------------------------------------------------------
_VALID_STATES = {
    "AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA","HI","ID","IL","IN",
    "IA","KS","KY","LA","ME","MD","MA","MI","MN","MS","MO","MT","NE","NV",
    "NH","NJ","NM","NY","NC","ND","OH","OK","OR","PA","RI","SC","SD","TN",
    "TX","UT","VT","VA","WA","WV","WI","WY","DC",
}

_BIZ_TYPES = {"sole_proprietor", "llc", "corporation", "nonprofit"}
_USE_OF_FUNDS = {"payroll", "rent_utilities", "equipment", "inventory", "other"}


def _validate_candidate(field: str, value: str) -> bool:
    """Return True if the extracted value is acceptable for the named field."""
    v = value.strip()
    if not v or _is_injection(v):
        return False
    if field == "business_name":
        return 2 <= len(v) <= 200
    if field == "business_type":
        return v in _BIZ_TYPES
    if field == "year_founded":
        try:
            yr = int(v)
            return 1800 <= yr <= 2025
        except ValueError:
            return False
    if field == "state":
        return v.upper() in _VALID_STATES
    if field == "ein":
        return bool(re.match(r"^\d{2}-\d{7}$", v))
    if field == "annual_revenue":
        try:
            return float(v) >= 0
        except ValueError:
            return False
    if field == "employee_count":
        try:
            return int(float(v)) >= 0
        except ValueError:
            return False
    if field == "revenue_drop_pct":
        try:
            return 0 <= float(v) <= 100
        except ValueError:
            return False
    if field == "use_of_funds":
        return v in _USE_OF_FUNDS
    if field == "use_of_funds_detail":
        return len(v) <= 500
    if field == "applicant_name":
        return 1 <= len(v) <= 200
    if field == "applicant_email":
        return bool(re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", v.lower()))
    return True


# ---------------------------------------------------------------------------
# Regex extractor helpers
# ---------------------------------------------------------------------------

def _extract_ein(text: str) -> str | None:
    m = re.search(r"\b(\d{2}-\d{7})\b", text)
    return m.group(1) if m else None


def _extract_dollar(text: str, *keywords: str) -> str | None:
    """Find a dollar amount on the same line as one of the given keywords."""
    for kw in keywords:
        pattern = re.compile(
            r"(?i)" + re.escape(kw) + r".*?\$?\s*([\d,]+(?:\.\d{1,2})?)",
            re.I,
        )
        m = pattern.search(text)
        if m:
            raw = m.group(1).replace(",", "")
            try:
                return str(float(raw))
            except ValueError:
                continue
    return None


def _extract_integer(text: str, *keywords: str) -> str | None:
    """Find an integer near one of the given keywords."""
    for kw in keywords:
        pattern = re.compile(
            r"(?i)" + re.escape(kw) + r"[^\d\n]{0,30}(\d{1,5})\b",
            re.I,
        )
        m = pattern.search(text)
        if m:
            return m.group(1)
    return None


def _extract_year(text: str, *keywords: str) -> str | None:
    for kw in keywords:
        pattern = re.compile(
            r"(?i)" + re.escape(kw) + r"[^\d\n]{0,30}((?:19|20)\d{2})\b",
            re.I,
        )
        m = pattern.search(text)
        if m:
            return m.group(1)
    return None


def _extract_state(text: str) -> str | None:
    """Match a two-letter US state code near common address keywords."""
    # Try address-line pattern first: "City, ST  ZIP"
    m = re.search(r",\s+([A-Z]{2})\s+\d{5}", text)
    if m and m.group(1) in _VALID_STATES:
        return m.group(1)
    # Try explicit "state:" label
    m = re.search(r"(?i)(?:state|st\.?)[:\s]+([A-Z]{2})\b", text)
    if m and m.group(1).upper() in _VALID_STATES:
        return m.group(1).upper()
    return None


def _extract_business_name(text: str) -> str | None:
    """Attempt to extract business/legal name from common heading patterns."""
    patterns = [
        r"(?i)(?:legal\s+)?business\s+name[:\s]+([^\n]{2,80})",
        r"(?i)name\s+of\s+(?:the\s+)?business[:\s]+([^\n]{2,80})",
        r"(?i)(?:applicant|taxpayer)\s+name[:\s]+([^\n]{2,80})",
    ]
    for p in patterns:
        m = re.search(p, text)
        if m:
            name = m.group(1).strip().rstrip(".,;")
            if 2 <= len(name) <= 200 and not _is_injection(name):
                return name
    return None


# ---------------------------------------------------------------------------
# Per-document-type field extraction maps
# ---------------------------------------------------------------------------

def _parse_tax_return(text: str) -> dict[str, str]:
    candidates: dict[str, str] = {}

    name = _extract_business_name(text)
    if name:
        candidates["business_name"] = name

    ein = _extract_ein(text)
    if ein:
        candidates["ein"] = ein

    rev = _extract_dollar(
        text,
        "gross receipts",
        "total income",
        "total revenue",
        "gross income",
        "net sales",
    )
    if rev:
        candidates["annual_revenue"] = rev

    emp = _extract_integer(text, "number of employees", "employees", "w-2")
    if emp:
        candidates["employee_count"] = emp

    yr = _extract_year(text, "tax year", "year ending", "fiscal year", "year ended")  # noqa: F841

    state = _extract_state(text)
    if state:
        candidates["state"] = state

    # Business type hints from form names
    text_lower = text.lower()
    if "1120-s" in text_lower or "s corporation" in text_lower:
        candidates["business_type"] = "corporation"
    elif "1120" in text_lower and "1120-s" not in text_lower:
        candidates["business_type"] = "corporation"
    elif "1065" in text_lower or "partnership" in text_lower:
        candidates["business_type"] = "llc"
    elif "1040" in text_lower and "schedule c" in text_lower:
        candidates["business_type"] = "sole_proprietor"
    elif "990" in text_lower or "nonprofit" in text_lower or "not-for-profit" in text_lower:
        candidates["business_type"] = "nonprofit"

    return candidates


def _parse_bank_statement(text: str) -> dict[str, str]:
    candidates: dict[str, str] = {}

    name = _extract_business_name(text) or _extract_account_holder(text)
    if name:
        candidates["business_name"] = name

    # Annual revenue from total deposits (multiply monthly by 12)
    monthly = _extract_dollar(
        text,
        "total deposits",
        "total credits",
        "deposits this period",
        "total deposit",
    )
    if monthly:
        try:
            annual = float(monthly) * 12
            candidates["annual_revenue"] = f"{annual:.2f}"
        except ValueError:
            pass

    state = _extract_state(text)
    if state:
        candidates["state"] = state

    return candidates


def _extract_account_holder(text: str) -> str | None:
    """Pull account holder / customer name from a bank statement."""
    patterns = [
        r"(?i)account\s+(?:holder|owner|name)[:\s]+([^\n]{2,80})",
        r"(?i)customer\s+name[:\s]+([^\n]{2,80})",
    ]
    for p in patterns:
        m = re.search(p, text)
        if m:
            name = m.group(1).strip().rstrip(".,;")
            if 2 <= len(name) <= 200 and not _is_injection(name):
                return name
    return None


# ---------------------------------------------------------------------------
# Text extraction from file
# ---------------------------------------------------------------------------

def _text_from_pdf(path: Path) -> str:
    """Extract all text from a PDF file via pdfplumber."""
    try:
        import pdfplumber  # type: ignore[import]
    except ImportError:
        _log.warning("pdfplumber not installed; PDF extraction unavailable.")
        return ""
    try:
        with pdfplumber.open(path) as pdf:
            parts = [page.extract_text() or "" for page in pdf.pages]
        return "\n".join(parts)
    except Exception as exc:
        _log.warning("pdfplumber failed on %s: %s", path.name, exc)
        return ""


def _text_from_image(path: Path) -> str:
    """Extract text from an image file via pytesseract (best-effort)."""
    try:
        import pytesseract  # type: ignore[import]
        from PIL import Image  # type: ignore[import]
    except ImportError:
        _log.warning("pytesseract/Pillow not installed; image OCR unavailable.")
        return ""
    try:
        img = Image.open(path)
        return pytesseract.image_to_string(img)
    except Exception as exc:
        _log.warning("pytesseract failed on %s: %s", path.name, exc)
        return ""


def _get_text(path: Path) -> str:
    """Route to the correct extractor based on file suffix."""
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return _text_from_pdf(path)
    if suffix in {".png", ".jpg", ".jpeg", ".tiff", ".tif"}:
        return _text_from_image(path)
    _log.warning("Unsupported file type: %s", suffix)
    return ""


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def extract_fields(file_path: Path, document_type: str) -> dict[str, str]:
    """Extract and sanitise grant-relevant fields from a PDF or image file.

    Returns a dict of {field_name: value} where every value has passed
    field-level validation.  Raw OCR text never leaves this function.

    Args:
        file_path: Absolute path to the uploaded file.
        document_type: "tax_return" or "bank_statement".

    Returns:
        Dict of validated field name → value pairs.  Empty dict on failure.
    """
    if not file_path.exists():
        _log.warning("extract_fields: file not found: %s", file_path)
        return {}

    text = _get_text(file_path)
    if not text.strip():
        _log.warning("extract_fields: no text extracted from %s", file_path.name)
        return {}

    # Select parser
    if document_type == "tax_return":
        candidates = _parse_tax_return(text)
    elif document_type == "bank_statement":
        candidates = _parse_bank_statement(text)
    else:
        _log.warning("extract_fields: unknown document_type: %s", document_type)
        return {}

    # Validate each candidate — only accepted values leave this function
    result: dict[str, str] = {}
    for field, value in candidates.items():
        clean = str(value).strip()
        if _validate_candidate(field, clean):
            result[field] = clean
        else:
            _log.debug("extract_fields: dropped invalid candidate %s=%r", field, clean)

    return result

"""App-wide settings loaded from .env at project root.

Import this module early (main.py does it at startup).
All other modules should read values from here rather than calling
os.getenv() directly so that the .env load happens exactly once.
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# Load .env from the project root (one level above this file's package)
_env_path = Path(__file__).parent.parent / ".env"
load_dotenv(_env_path, override=False)  # don't override real env vars in prod

# ── App security ───────────────────────────────────────────────────────────
SECRET_KEY: str = os.getenv("SECRET_KEY", "dev-secret-paperpilot-change-in-prod")

# ── Storage ────────────────────────────────────────────────────────────────
UPLOADS_DIR: Path = Path(os.getenv("UPLOADS_DIR", "uploads"))
DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///./paperpilot.db")

# ── Cookie security ────────────────────────────────────────────────────────
# Set COOKIE_SECURE=true in production (HTTPS only). False in dev (HTTP).
COOKIE_SECURE: bool = os.getenv("COOKIE_SECURE", "false").lower() == "true"

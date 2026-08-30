"""Session cookie and CSRF token utilities.

Cookie name: paperpilot_session (HttpOnly, SameSite=Lax)
CSRF tokens: itsdangerous URLSafeSerializer keyed on session_id.
             Embedded in every mutating HTML form as <input name="_csrf">.
"""

from __future__ import annotations

from itsdangerous import BadSignature, URLSafeSerializer

from app.settings import SECRET_KEY

COOKIE_NAME = "paperpilot_session"
COOKIE_MAX_AGE = 60 * 60 * 24 * 7  # 7 days

_csrf = URLSafeSerializer(SECRET_KEY, salt="csrf-v1")


def generate_csrf_token(session_id: str) -> str:
    return _csrf.dumps(session_id)


def verify_csrf_token(token: str, session_id: str) -> bool:
    try:
        return _csrf.loads(token) == session_id
    except BadSignature:
        return False

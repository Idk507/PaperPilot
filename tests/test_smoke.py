"""Phase 0 smoke test — verifies the app boots and serves a 200 from /.

Run with: pytest tests/ -q
"""

from starlette.testclient import TestClient

from app.main import app


def test_root_returns_200():
    with TestClient(app) as client:
        response = client.get("/")
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"


def test_root_html_content():
    with TestClient(app) as client:
        response = client.get("/")
    assert "PaperPilot" in response.text


def test_app_imports_cleanly():
    """Verifies all routers and models import without errors."""
    import app.main  # noqa: F401
    import app.db    # noqa: F401
    import app.models  # noqa: F401

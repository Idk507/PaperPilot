"""Form router — CRUD for sessions and field values.

Phase 0: stub that returns a placeholder response.
Full implementation in Phase 1.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

router = APIRouter(prefix="/form", tags=["form"])


@router.get("/", response_class=HTMLResponse)
async def form_root(request: Request):
    return HTMLResponse("<h1>Form — coming in Phase 1</h1>")

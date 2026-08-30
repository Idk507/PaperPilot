"""FastAPI application entry point."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlmodel import SQLModel

import app.settings
from app.db import (  # noqa: F401 — ensures all tables are registered before create_all
    Document,
    FieldValue,
    FormSession,
    ToolCallLog,
    engine,
)
from app.routers import audit, documents, eligibility, explain, form
from app.settings import UPLOADS_DIR


@asynccontextmanager
async def lifespan(app: FastAPI):
    SQLModel.metadata.create_all(engine)
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(
    title="PaperPilot",
    description="WebMCP-powered grant application form.",
    version="0.1.0",
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")


@app.middleware("http")
async def webmcp_headers(request: Request, call_next):
    """Allow the in-page WebMCP tools Permissions Policy on this origin."""
    response = await call_next(request)
    response.headers["Permissions-Policy"] = "tools=*"
    return response

app.include_router(form.router)
app.include_router(form.api_router)
app.include_router(eligibility.router)
app.include_router(documents.router)
app.include_router(explain.router)
app.include_router(audit.router)


@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    return templates.TemplateResponse(request, "home.html")


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    from app.db import FieldValue, get_db
    from app.services.rules_engine import (
        calculate_award_estimate,
        check_eligibility,
        get_application_checklist,
    )
    from app.services.session_utils import COOKIE_NAME, generate_csrf_token
    from sqlmodel import Session as _Sess, select

    sid = request.cookies.get(COOKIE_NAME)
    checklist  = {"sections": [], "completion_pct": 0, "missing_required": [], "total_required": 0, "total_filled": 0}
    elig_data  = {"eligible": None, "reasons": []}
    est_data   = {"eligible": None, "range_low": 0, "range_high": 0, "tier_label": "—", "notes": []}

    if sid:
        with _Sess(engine) as db:
            try:
                checklist  = get_application_checklist(sid, db)
            except Exception:
                pass
            try:
                elig_data  = check_eligibility(sid, db)
            except Exception:
                pass
            try:
                rows = db.exec(
                    select(FieldValue).where(
                        FieldValue.session_id == sid,
                        FieldValue.committed.is_(True),
                    )
                ).all()
                values = {r.field_name: r.value for r in rows}
                revenue = float(values.get("annual_revenue") or 0) or None
                drop    = float(values.get("revenue_drop_pct") or 0) or None
                emp     = int(float(values.get("employee_count") or 0)) or None
                if revenue and drop and emp:
                    est_data = calculate_award_estimate(revenue, drop, emp)
            except Exception:
                pass

    csrf = generate_csrf_token(sid or "anon")
    return templates.TemplateResponse(request, "dashboard.html", {
        "sid":        sid,
        "checklist":  checklist,
        "eligibility": elig_data,
        "estimate":   est_data,
        "csrf_token": csrf,
    })

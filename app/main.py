"""FastAPI application entry point.

Mounts all routers and static files. Creates the SQLite database tables on
startup. Serves Jinja2 templates for the human-facing form UI.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# ---------------------------------------------------------------------------
# Engine import must happen after all table models are imported above.
# ---------------------------------------------------------------------------
from sqlmodel import SQLModel, create_engine

from app.db import (  # noqa: F401 — ensure tables register
    FieldValue,
    Session,
    ToolCallLog,
)
from app.routers import audit, documents, eligibility, explain, form

DATABASE_URL = "sqlite:///./paperpilot.db"
engine = create_engine(DATABASE_URL, echo=False, connect_args={"check_same_thread": False})


@asynccontextmanager
async def lifespan(app: FastAPI):
    SQLModel.metadata.create_all(engine)
    yield


app = FastAPI(
    title="PaperPilot",
    description="WebMCP-powered grant application form.",
    version="0.1.0",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# Static files and templates
# ---------------------------------------------------------------------------
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

# ---------------------------------------------------------------------------
# Routers
# ---------------------------------------------------------------------------
app.include_router(form.router)
app.include_router(eligibility.router)
app.include_router(documents.router)
app.include_router(explain.router)
app.include_router(audit.router)


# ---------------------------------------------------------------------------
# Root — redirect into the form
# ---------------------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    # Starlette 1.x API: request is the first positional argument
    return templates.TemplateResponse(request, "home.html")

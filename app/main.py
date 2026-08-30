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

app.include_router(form.router)
app.include_router(eligibility.router)
app.include_router(documents.router)
app.include_router(explain.router)
app.include_router(audit.router)


@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    return templates.TemplateResponse(request, "home.html")

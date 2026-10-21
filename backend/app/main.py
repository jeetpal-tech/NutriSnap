"""
main.py - FastAPI application entry point for NutriSnap.

Start the server:
    uvicorn app.main:app --port 8000

Rules-only (no model):
    ML_ENABLED=false uvicorn app.main:app --port 8000
    # PowerShell: $env:ML_ENABLED="false"; uvicorn app.main:app --port 8000
"""
from __future__ import annotations

import logging
import re
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.routes import router, set_knowledge_base
from app.config import settings
from app.core.knowledge_base import KnowledgeBase

logging.basicConfig(
    level=settings.log_level.upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Load the knowledge base at startup. ML loading comes in M3."""
    logger.info("NutriSnap startup — loading knowledge base …")
    kb = KnowledgeBase()
    kb.load()
    set_knowledge_base(kb)
    logger.info(
        "Knowledge base loaded: %d entries (version %d)",
        len(kb.entries),
        kb.version,
    )
    yield
    logger.info("NutriSnap shutdown.")


app = FastAPI(
    title="NutriSnap API",
    description=(
        "Packaged-food ingredient health analyser for Indian consumers. "
        "Academic mini-project — not medical advice."
    ),
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url=None,
)

# ── CORS ───────────────────────────────────────────────────────────────────────
_origins = settings.cors_origins_list()
_origin_regex = settings.cors_origin_regex or None

# Build middleware kwargs
_cors_kwargs: dict = dict(
    allow_origins=_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Accept"],
)
if _origin_regex:
    _cors_kwargs["allow_origin_regex"] = _origin_regex

app.add_middleware(CORSMiddleware, **_cors_kwargs)

# ── Routes ─────────────────────────────────────────────────────────────────────
app.include_router(router)


# ── Global error handler (ML exceptions must never produce HTTP 500 traces) ───
@app.exception_handler(Exception)
async def _global_error(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled exception on %s %s", request.method, request.url)
    return JSONResponse(status_code=500, content={"detail": "internal_error"})

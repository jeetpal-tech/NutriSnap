"""
conftest.py - Shared fixtures for NutriSnap tests.

All tests in this suite are deterministic and do not require the ML model
or a network connection (ARCHITECTURE §12).
"""
from __future__ import annotations

import pytest
from app.config import settings
from app.core.knowledge_base import KnowledgeBase
from app.core.ml.manager import set_model


@pytest.fixture(scope="session")
def kb() -> KnowledgeBase:
    """Loaded KnowledgeBase (session-scoped — loaded once for all tests)."""
    instance = KnowledgeBase()
    instance.load()
    return instance


@pytest.fixture(autouse=True)
def disable_live_gemini(monkeypatch):
    """Unit/API tests never spend provider quota; provider tests opt in."""
    monkeypatch.setattr(settings, "gemini_api_key", "")
    set_model(None)
    yield
    set_model(None)

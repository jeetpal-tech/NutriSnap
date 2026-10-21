"""
conftest.py - Shared fixtures for NutriSnap tests.

All tests in this suite are deterministic and do not require the ML model
or a network connection (ARCHITECTURE §12).
"""
from __future__ import annotations

import pytest
from app.core.knowledge_base import KnowledgeBase


@pytest.fixture(scope="session")
def kb() -> KnowledgeBase:
    """Loaded KnowledgeBase (session-scoped — loaded once for all tests)."""
    instance = KnowledgeBase()
    instance.load()
    return instance

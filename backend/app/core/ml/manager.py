"""
manager.py - Model lifecycle manager and stub adapter (ARCHITECTURE §7.4).
"""
from __future__ import annotations

import logging
import threading
from typing import Literal

from app.config import settings
from app.core.ml.base import ModelError, NovaModel, NovaPrediction

logger = logging.getLogger(__name__)


class StubNovaModel:
    """
    Default stub adapter when no real model or mock is loaded.
    Always reports status 'disabled'.
    """

    status: Literal["loading", "ready", "error", "disabled"] = "disabled"
    is_stub: bool = True
    model_id: str = "stub"

    def load(self) -> None:
        pass

    def predict(self, text: str) -> NovaPrediction:
        raise ModelError("Configured ML adapter is still a stub.")


_current_model: NovaModel | None = None


def get_model() -> NovaModel:
    """Return the adapter selected by NOVA_BACKEND; current adapters are stubs."""
    global _current_model
    if _current_model is None:
        if settings.nova_backend == "minilm_head":
            from app.core.ml.minilm_head import MiniLMHeadModel
            _current_model = MiniLMHeadModel()
        else:
            from app.core.ml.hf_nova import HfNovaModel
            _current_model = HfNovaModel()
    return _current_model


def set_model(model: NovaModel | None) -> None:
    """Register a NovaModel instance (e.g. MockNovaModel in tests)."""
    global _current_model
    _current_model = model


def init_background_model_loader(model: NovaModel | None = None) -> None:
    """
    Call model.load() in a background thread at app startup per ARCHITECTURE §7.4.
    If the adapter is a stub or ML_ENABLED=false, status remains 'disabled'.
    """
    if model is None:
        model = get_model()

    if not settings.ml_enabled or getattr(model, "is_stub", False) or model.status == "disabled":
        model.status = "disabled"
        return

    model.status = "loading"

    def _loader() -> None:
        try:
            logger.info("Background model loader: starting model.load() ...")
            model.load()
            model.status = "ready"
            logger.info("Background model loader: model is ready.")
        except Exception:
            logger.exception("Background model loader failed:")
            model.status = "error"

    loader_thread = threading.Thread(target=_loader, name="ml-loader-thread", daemon=True)
    loader_thread.start()

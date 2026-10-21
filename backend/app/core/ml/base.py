"""
base.py - ML adapter protocol and shared dataclasses (ARCHITECTURE §7.4).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Protocol


@dataclass
class NovaPrediction:
    """NOVA prediction output from any ML adapter."""
    probs: dict[int, float]    # {1: p1, 2: p2, 3: p3, 4: p4}, sums to ~1.0
    top: int                    # Predicted NOVA group (1-4)
    confidence: float           # probs[top]
    margin: float               # top1_prob - top2_prob
    latency_ms: int
    model_id: str


class ModelNotReady(Exception):
    """Raised by predict() when the model is still loading."""


class ModelError(Exception):
    """Raised by predict() on any model inference failure."""


class NovaModel(Protocol):
    status: Literal["loading", "ready", "error", "disabled"]

    def load(self) -> None:
        """Called in a background thread at startup."""
        ...

    def predict(self, text: str) -> NovaPrediction:
        """Raises ModelNotReady or ModelError; never raises arbitrarily."""
        ...

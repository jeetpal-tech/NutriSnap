"""
mocks.py - MockNovaModel for testing without loading real models (M3a).
"""
from __future__ import annotations

import time
from typing import Literal

from app.core.ml.base import ModelError, ModelNotReady, NovaModel, NovaPrediction


class MockNovaModel:
    """
    Mock implementation of NovaModel protocol for unit and integration tests.
    Allows configuring status, predictions, latencies, and exceptions per test.
    """

    def __init__(
        self,
        status: Literal["loading", "ready", "error", "disabled"] = "ready",
        model_id: str = "mock-nova@test",
    ):
        self.status: Literal["loading", "ready", "error", "disabled"] = status
        self.model_id = model_id
        self.load_calls: int = 0
        self.predict_calls: list[str] = []
        self.load_exception: Exception | None = None
        self.predict_exception: Exception | None = None
        self.delay_s: float = 0.0

        # Default prediction: NOVA 4 with high confidence and healthy margin
        self._prediction: NovaPrediction = NovaPrediction(
            probs={1: 0.01, 2: 0.02, 3: 0.04, 4: 0.93},
            top=4,
            confidence=0.93,
            margin=0.89,
            latency_ms=10,
            model_id=self.model_id,
        )

    def load(self) -> None:
        self.load_calls += 1
        if self.load_exception:
            self.status = "error"
            raise self.load_exception
        self.status = "ready"

    def predict(self, text: str) -> NovaPrediction:
        self.predict_calls.append(text)
        if self.delay_s > 0:
            time.sleep(self.delay_s)

        if self.status == "loading":
            raise ModelNotReady("Model is still loading")
        if self.status == "error":
            raise ModelError("Model failed to load or encountered error")
        if self.status == "disabled":
            raise ModelError("Model is disabled")

        if self.predict_exception:
            raise self.predict_exception

        return self._prediction

    def set_prediction(
        self,
        top: int = 4,
        confidence: float = 0.93,
        margin: float = 0.89,
        probs: dict[int, float] | None = None,
        latency_ms: int = 10,
    ) -> None:
        if probs is None:
            other = round((1.0 - confidence) / 3.0, 4)
            probs = {i: other for i in (1, 2, 3, 4)}
            # ensure sum is exactly 1.0 by adjusting last
            rem = round(1.0 - confidence - (other * 2), 4)
            non_top = [i for i in (1, 2, 3, 4) if i != top]
            probs[non_top[-1]] = rem
            probs[top] = confidence
        self._prediction = NovaPrediction(
            probs=probs,
            top=top,
            confidence=confidence,
            margin=margin,
            latency_ms=latency_ms,
            model_id=self.model_id,
        )

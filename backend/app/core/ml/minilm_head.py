"""
minilm_head.py - Plan B ML adapter: MiniLM encoder + trained head (stub; M3).
Used only if the Plan A spike fails (ARCHITECTURE §7.1 Plan B).
"""
from app.core.ml.base import ModelError


class MiniLMHeadModel:
    """Unavailable adapter placeholder. It performs no download or inference."""
    status = "disabled"
    is_stub = True
    model_id = "minilm-head-stub"

    def load(self) -> None:
        return None

    def predict(self, text: str):
        raise ModelError("The MiniLM head adapter is not implemented.")

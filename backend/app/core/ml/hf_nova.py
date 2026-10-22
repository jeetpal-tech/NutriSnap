"""
hf_nova.py - Plan A ML adapter: hsilvosa/nova-group-classifier (stub; M3).
Pinned revision: f252e3546650954596ff7e5926aab4559c433909
"""
from app.core.ml.base import ModelError


class HfNovaModel:
    """Unavailable adapter placeholder. It performs no download or inference."""
    status = "disabled"
    is_stub = True
    model_id = "hf_hsilvosa-stub"

    def load(self) -> None:
        return None

    def predict(self, text: str):
        raise ModelError("The HF NOVA adapter is not implemented.")

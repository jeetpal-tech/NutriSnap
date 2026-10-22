"""CPU MiniLM encoder plus a numeric softmax head stored in NPZ format."""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from app.config import settings
from app.core.ml.base import ModelError, NovaPrediction

logger = logging.getLogger(__name__)
ENCODER_ID = "sentence-transformers/all-MiniLM-L6-v2"
SELF_TESTS = [
    ("wheat", 1), ("whole milk", 1),
    ("sugar", 2), ("refined palm oil", 2), ("salt", 2),
    ("wheat flour, water, yeast, salt", 3), ("chickpeas, water, salt", 3),
    ("instant noodles, palm oil, salt, flavour enhancer 621, flavour enhancer 627", 4),
    ("wheat flour, invert sugar, vegetable oil, emulsifier 471", 4),
    ("carbonated water, sugar, caramel colour, phosphoric acid, flavouring", 4),
    ("potato, palm oil, salt, maltodextrin, flavour enhancer 621", 4),
    ("water, sugar, fruit juice concentrate, stabiliser 415, flavouring", 4),
]


class MiniLMHeadModel:
    status = "disabled"
    is_stub = False
    model_id = "minilm-head"

    def __init__(self, model_dir: str | Path | None = None) -> None:
        self.model_dir = Path(model_dir) if model_dir is not None else Path(settings.nova_model_dir)
        if not self.model_dir.is_absolute():
            if self.model_dir.exists():
                self.model_dir = self.model_dir.resolve()
            else:
                repo_root = Path(__file__).resolve().parents[4]
                self.model_dir = (repo_root / self.model_dir).resolve()
        self.encoder_dir = self.model_dir.parent / "minilm-encoder"
        self.error_reason: str | None = None
        self.np: Any = None
        self.tokenizer: Any = None
        self.encoder: Any = None
        self.coef: np.ndarray | None = None
        self.intercept: np.ndarray | None = None
        self.classes: np.ndarray | None = None
        self._torch: Any = None

    def load(self) -> None:
        """Load local head and encoder, downloading encoder once if absent, then self-test."""
        try:
            import numpy as np
            import torch
            from transformers import AutoModel, AutoTokenizer

            torch.set_num_threads(2)
            torch.manual_seed(0)
            self._torch = torch
            self.np = np
            self.model_dir.mkdir(parents=True, exist_ok=True)
            self.encoder_dir.mkdir(parents=True, exist_ok=True)
            config_path = self.model_dir / "head_config.json"
            npz_path = self.model_dir / "head.npz"
            if not config_path.is_file() or not npz_path.is_file():
                raise FileNotFoundError(f"MiniLM head files missing from {self.model_dir}")
            head_config = json.loads(config_path.read_text(encoding="utf-8"))
            with np.load(npz_path, allow_pickle=False) as arrays:
                self.coef = np.asarray(arrays["coef"], dtype=np.float32)
                self.intercept = np.asarray(arrays["intercept"], dtype=np.float32)
                self.classes = np.asarray(arrays["classes"], dtype=np.int64)
            expected_classes = np.asarray(head_config.get("classes", []), dtype=np.int64)
            if (self.coef.shape != (4, 384) or self.intercept.shape != (4,) or
                    not np.array_equal(self.classes, expected_classes) or
                    not np.array_equal(self.classes, np.array([1, 2, 3, 4])) or
                    not np.isfinite(self.coef).all() or not np.isfinite(self.intercept).all()):
                raise ValueError("MiniLM head array shape, classes, or values are invalid")

            local_ready = all((self.encoder_dir / f).exists() for f in ("config.json", "tokenizer.json", "model.safetensors"))
            if local_ready:
                self.tokenizer = AutoTokenizer.from_pretrained(str(self.encoder_dir), local_files_only=True)
                self.encoder = AutoModel.from_pretrained(str(self.encoder_dir), local_files_only=True)
            else:
                # Download only at startup, save to the local model directory, and use local files thereafter.
                self.tokenizer = AutoTokenizer.from_pretrained(ENCODER_ID)
                self.encoder = AutoModel.from_pretrained(ENCODER_ID)
                self.tokenizer.save_pretrained(str(self.encoder_dir))
                self.encoder.save_pretrained(str(self.encoder_dir), safe_serialization=True)
            self.encoder.eval()
            self.model_id = f"{ENCODER_ID}+minilm-head"
            outcomes = [self.predict(sample) for sample, _ in SELF_TESTS]
            non_nova2 = [(pred.top, expected) for pred, (_, expected) in zip(outcomes, SELF_TESTS) if expected != 2]
            correct = sum(actual == expected for actual, expected in non_nova2)
            median_conf = float(np.median([p.confidence for p in outcomes]))
            if correct < 8 or median_conf < 0.70:
                self.error_reason = "selftest_failed"
                raise ModelError("MiniLM startup self-test failed")
            logger.info("MiniLM startup self-test passed (%d/%d non-NOVA-2, median confidence %.3f)", correct, len(non_nova2), median_conf)
        except Exception:
            if self.error_reason != "selftest_failed":
                self.error_reason = "model_load_failed"
            raise

    def _embedding(self, text: str) -> np.ndarray:
        if self.tokenizer is None or self.encoder is None or self._torch is None:
            raise ModelError("MiniLM encoder is not loaded")
        torch = self._torch
        inputs = self.tokenizer(text, return_tensors="pt", truncation=True, max_length=256)
        with torch.inference_mode():
            output = self.encoder(**inputs)
            hidden = output.last_hidden_state
            mask = inputs["attention_mask"].unsqueeze(-1).to(hidden.dtype)
            pooled = (hidden * mask).sum(dim=1) / mask.sum(dim=1).clamp(min=1)
            embedding = torch.nn.functional.normalize(pooled, p=2, dim=1)
        return embedding[0].detach().cpu().numpy().astype(np.float32, copy=False)

    def predict(self, text: str) -> NovaPrediction:
        if self.np is None or self.coef is None or self.intercept is None or self.classes is None:
            raise ModelError("MiniLM head is not loaded")
        np = self.np
        started = time.perf_counter()
        try:
            embedding = self._embedding(text)
            if embedding.shape != (384,) or not np.isfinite(embedding).all():
                raise ValueError("Encoder returned an invalid embedding")
            logits = embedding @ self.coef.T + self.intercept
            logits = logits - np.max(logits)
            exp_logits = np.exp(logits)
            probs = exp_logits / exp_logits.sum()
            order = np.argsort(probs)[::-1]
            top_idx = int(order[0])
            pvals = [float(x) for x in probs]
            return NovaPrediction(
                probs={int(self.classes[i]): pvals[i] for i in range(4)},
                top=int(self.classes[top_idx]), confidence=pvals[top_idx],
                margin=pvals[int(order[0])] - pvals[int(order[1])],
                latency_ms=int((time.perf_counter() - started) * 1000), model_id=self.model_id,
            )
        except ModelError:
            raise
        except Exception as exc:
            raise ModelError("MiniLM inference failed") from exc

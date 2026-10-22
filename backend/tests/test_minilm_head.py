import json
from pathlib import Path
from uuid import uuid4

import pytest

np = pytest.importorskip("numpy")
from app.core.ml.minilm_head import MiniLMHeadModel


def test_numeric_npz_head_and_synthetic_prediction():
    folder = Path(__file__).parents[1] / "data" / f"head-test-{uuid4().hex}"
    folder.mkdir(parents=True)
    try:
        (folder / "head_config.json").write_text(json.dumps({"encoder": "synthetic", "normalize": True, "classes": [1, 2, 3, 4]}), encoding="utf-8")
        coef = np.zeros((4, 384), dtype=np.float32)
        coef[3, 0] = 2.0
        np.savez(folder / "head.npz", coef=coef, intercept=np.zeros(4, dtype=np.float32), classes=np.array([1, 2, 3, 4]))
        model = MiniLMHeadModel(folder)
        with np.load(folder / "head.npz", allow_pickle=False) as arrays:
            model.coef = arrays["coef"].copy()
            model.intercept = arrays["intercept"].copy()
            model.classes = arrays["classes"].copy()
        model.np = np
        model.model_id = "synthetic"
        vector = np.zeros(384, dtype=np.float32)
        vector[0] = 1.0
        model._embedding = lambda text: vector
        result = model.predict("synthetic ingredient text")
        assert result.top == 4
        assert set(result.probs) == {1, 2, 3, 4}
        assert sum(result.probs.values()) == pytest.approx(1.0)
        assert result.confidence > result.probs[1]
    finally:
        for child in folder.iterdir():
            child.unlink()
        folder.rmdir()

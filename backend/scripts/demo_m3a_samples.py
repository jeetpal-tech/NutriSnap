"""
demo_m3a_samples.py - Generate and display TestClient outputs for the 6 required M3a scenarios.
"""
import json
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi.testclient import TestClient

from app.api.routes import set_knowledge_base
from app.core.knowledge_base import KnowledgeBase
from app.core.ml.manager import set_model
from app.main import app
from tests.mocks import MockNovaModel


def run():
    kb = KnowledgeBase()
    kb.load()
    set_knowledge_base(kb)

    client = TestClient(app)

    # 1. ML accepted (mock)
    mock = MockNovaModel(status="ready")
    mock.set_prediction(top=4, confidence=0.93, margin=0.89)
    set_model(mock)
    r1 = client.post(
        "/api/analyze",
        json={"ingredients_text": "Refined wheat flour (maida) (61%), Sugar, Palm oil, Salt"},
    )
    print("=== 1. ML ACCEPTED (MOCK) ===")
    print(json.dumps(r1.json(), indent=2))

    # 2. Low confidence
    mock.set_prediction(
        top=4,
        confidence=0.52,
        margin=0.20,
        probs={1: 0.10, 2: 0.10, 3: 0.28, 4: 0.52},
    )
    set_model(mock)
    r2 = client.post(
        "/api/analyze",
        json={"ingredients_text": "Refined wheat flour (maida) (61%), Sugar, Palm oil, Salt"},
    )
    print("\n=== 2. LOW CONFIDENCE ===")
    print(json.dumps(r2.json(), indent=2))

    # 3. Forced rules
    r3 = client.post(
        "/api/analyze",
        json={
            "ingredients_text": "Refined wheat flour (maida) (61%), Sugar, Palm oil, Salt",
            "force_mode": "rules",
        },
    )
    print("\n=== 3. FORCED RULES ===")
    print(json.dumps(r3.json(), indent=2))

    # 4. Model failing
    mock.predict_exception = RuntimeError("Internal CUDA error / model failure")
    set_model(mock)
    r4 = client.post(
        "/api/analyze",
        json={"ingredients_text": "Refined wheat flour (maida) (61%), Sugar, Palm oil, Salt"},
    )
    print("\n=== 4. MODEL FAILING ===")
    print(json.dumps(r4.json(), indent=2))

    # 5. Insufficient input
    r5 = client.post(
        "/api/analyze",
        json={"ingredients_text": "Sugar"},
    )
    print("\n=== 5. INSUFFICIENT INPUT ===")
    print(json.dumps(r5.json(), indent=2))

    # 6. Not food text
    r6 = client.post(
        "/api/analyze",
        json={"ingredients_text": "Plastic casing, copper wiring, lithium battery"},
    )
    print("\n=== 6. NOT FOOD TEXT ===")
    print(json.dumps(r6.json(), indent=2))


if __name__ == "__main__":
    run()

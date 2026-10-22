import pytest

from app.config import settings
from app.core.ml.base import ModelError
from app.core.ml.manager import get_model, set_model


@pytest.mark.parametrize("backend,expected,is_stub", [("hf_hsilvosa", "hf_hsilvosa-stub", True), ("minilm_head", "minilm-head", False)])
def test_selected_adapter(monkeypatch, backend, expected, is_stub):
    set_model(None)
    monkeypatch.setattr(settings, "nova_backend", backend)
    model = get_model()
    assert model.status == "disabled"
    assert model.model_id == expected
    assert model.is_stub is is_stub
    with pytest.raises(ModelError):
        model.predict("wheat flour, salt")
    set_model(None)

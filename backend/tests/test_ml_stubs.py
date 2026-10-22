import pytest

from app.config import settings
from app.core.ml.base import ModelError
from app.core.ml.manager import get_model, set_model


@pytest.mark.parametrize("backend,expected", [("hf_hsilvosa", "hf_hsilvosa-stub"), ("minilm_head", "minilm-head-stub")])
def test_selected_adapter_is_disabled_stub(monkeypatch, backend, expected):
    set_model(None)
    monkeypatch.setattr(settings, "nova_backend", backend)
    model = get_model()
    assert model.status == "disabled"
    assert model.model_id == expected
    with pytest.raises(ModelError):
        model.predict("wheat flour, salt")
    set_model(None)

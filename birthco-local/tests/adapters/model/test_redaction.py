import httpx
import pytest

from backend.adapters.model.mimo import MiMoAdapter, ModelConfigurationError
from backend.adapters.model.protocol import ModelMessage, ModelRequest


SECRET = "sentinel-secret-value-123"


def test_network_exception_does_not_echo_key(caplog):
    def handler(request):
        raise httpx.ReadTimeout(f"failure with {SECRET}")
    req = ModelRequest(
        call_id="redaction-1", role="reviewer",
        messages=(ModelMessage("user", "test"),), model_id="model",
        max_completion_tokens=32, timeout_seconds=5, temperature=0,
        top_p=1, json_mode=False, mode="live",
    )
    with MiMoAdapter(api_key=SECRET, configured_model_id="model",
                     transport=httpx.MockTransport(handler)) as model:
        result = model.complete(req)
    assert result.status == "unknown"
    assert SECRET not in repr(result)
    assert SECRET not in caplog.text


def test_missing_credentials_never_enter_transport(monkeypatch):
    monkeypatch.delenv("MIMO_API_KEY", raising=False)
    with pytest.raises(ModelConfigurationError) as error:
        MiMoAdapter(api_key="   ", configured_model_id="model")
    assert SECRET not in str(error.value)

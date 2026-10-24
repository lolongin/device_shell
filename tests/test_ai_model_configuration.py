from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

from device_tui.application.ai.llm.configuration import AiModelConfiguration
from device_tui.application.ai.llm.openai import OpenAiCompatibleClient
from device_tui.application.ai.llm.models import LlmResponse
from device_tui.application.secrets import MemorySecretStore
from device_tui.application.settings import MemorySettingsStore
from device_tui.device_sources.sample import SampleDeviceRepository
from device_tui.interfaces.desktop_api.app import create_app
from device_tui.interfaces.desktop_api.session_hub import SessionHub


def test_model_configuration_keeps_key_in_secret_store(monkeypatch) -> None:
    monkeypatch.setenv("DEVICE_AI_API_KEY", "environment-key")
    settings = MemorySettingsStore()
    secrets = MemorySecretStore()
    config = AiModelConfiguration(settings, secrets)

    assert config.public()["key_source"] == "environment"
    config.update(base_url="https://api.deepseek.com", model="deepseek-flash", timeout=45)
    public = config.set_key("vault-key")

    assert public["has_api_key"] is True
    assert public["key_source"] == "vault"
    assert "vault-key" not in str(public)
    assert settings.get("ai.model.key_source") == "vault"
    assert secrets.get(config.KEY_ID) == "vault-key"
    assert config.client().api_key == "vault-key"

    config.delete_key()
    assert config.public()["has_api_key"] is False
    assert secrets.get(config.KEY_ID) is None
    assert config.client().api_key == ""


@pytest.mark.parametrize("url", ["file:///tmp/model", "https://user:pass@example.com", "https://example.com?token=x"])
def test_model_configuration_rejects_unsafe_urls(url: str) -> None:
    config = AiModelConfiguration(MemorySettingsStore(), MemorySecretStore())
    with pytest.raises(ValueError):
        config.update(base_url=url, model="model", timeout=60)


def test_model_api_updates_running_agent_without_returning_key(monkeypatch) -> None:
    monkeypatch.delenv("DEVICE_AI_API_KEY", raising=False)
    async def fake_chat(self, *, messages, tools):
        assert messages[-1]["content"] == "Reply with OK. Do not call a tool."
        assert tools[0]["function"]["name"] == "connection_check"
        return LlmResponse(text="OK", tool_calls=[], finish_reason="stop")

    monkeypatch.setattr(OpenAiCompatibleClient, "chat", fake_chat)
    app = create_app(token="model-test", repository=SampleDeviceRepository(), session_hub=SessionHub())
    headers = {"Authorization": "Bearer model-test"}
    with TestClient(app) as client:
        assert client.post("/api/v1/ai/model/test", headers=headers).status_code == 400
        updated = client.put("/api/v1/ai/model", headers=headers, json={
            "base_url": "https://api.deepseek.com", "model": "deepseek-flash", "timeout": 45,
        })
        key = client.put("/api/v1/ai/model-key", headers=headers, json={"api_key": "test-key"})
        fetched = client.get("/api/v1/ai/model", headers=headers)
        tested = client.post("/api/v1/ai/model/test", headers=headers)
        deleted = client.delete("/api/v1/ai/model-key", headers=headers)

    assert updated.status_code == 200
    assert key.status_code == 200
    assert fetched.json()["model"] == "deepseek-flash"
    assert tested.json() == {"success": True}
    assert "test-key" not in fetched.text
    assert app.state.context.ai_agent._llm.model == "deepseek-flash"
    assert deleted.json()["has_api_key"] is False

"""Persistent, secret-safe configuration for the desktop Agent model."""

from __future__ import annotations

import os
from urllib.parse import urlparse

from device_tui.application.secrets import SecretStore
from device_tui.application.settings import SettingsStore

from .openai import OpenAiCompatibleClient


class AiModelConfiguration:
    KEY_ID = "ai/model/api-key"

    def __init__(self, settings: SettingsStore, secrets: SecretStore) -> None:
        self.settings = settings
        self.secrets = secrets

    def public(self) -> dict:
        base_url = str(self.settings.get("ai.model.base_url") or os.getenv("DEVICE_AI_BASE_URL") or "https://api.openai.com/v1")
        model = str(self.settings.get("ai.model.name") or os.getenv("DEVICE_AI_MODEL") or "gpt-4o-mini")
        raw_timeout = self.settings.get("ai.model.timeout", os.getenv("DEVICE_AI_TIMEOUT", "60"))
        try:
            timeout = float(raw_timeout)
        except (TypeError, ValueError):
            timeout = 60.0
        source = self.settings.get("ai.model.key_source")
        stored_key = self.secrets.get(self.KEY_ID) if source == "vault" else None
        env_key = os.getenv("DEVICE_AI_API_KEY", "") if source is None else ""
        return {
            "base_url": base_url,
            "model": model,
            "timeout": timeout,
            "has_api_key": bool(stored_key or env_key),
            "key_source": "vault" if stored_key else "environment" if env_key else "none",
        }

    def client(self) -> OpenAiCompatibleClient:
        config = self.public()
        key = self.secrets.get(self.KEY_ID) if config["key_source"] == "vault" else (
            os.getenv("DEVICE_AI_API_KEY", "") if config["key_source"] == "environment" else ""
        )
        return OpenAiCompatibleClient(
            base_url=config["base_url"], api_key=key or "",
            model=config["model"], timeout=config["timeout"],
        )

    def update(self, *, base_url: str, model: str, timeout: float) -> dict:
        url = urlparse(base_url.strip())
        if url.scheme not in {"https", "http"} or not url.netloc or url.username or url.password or url.query or url.fragment:
            raise ValueError("Enter a valid HTTP(S) model API URL without credentials or query parameters")
        if not model.strip() or len(model) > 128 or len(base_url) > 2048 or not 1 <= timeout <= 300:
            raise ValueError("Invalid model name, API URL, or timeout")
        self.settings.set("ai.model.base_url", base_url.strip().rstrip("/"))
        self.settings.set("ai.model.name", model.strip())
        self.settings.set("ai.model.timeout", timeout)
        return self.public()

    def set_key(self, key: str) -> dict:
        if not key.strip() or len(key) > 4096:
            raise ValueError("Invalid API key")
        self.secrets.set(self.KEY_ID, key.strip())
        self.settings.set("ai.model.key_source", "vault")
        return self.public()

    def delete_key(self) -> dict:
        self.secrets.delete(self.KEY_ID)
        self.settings.set("ai.model.key_source", "none")
        return self.public()

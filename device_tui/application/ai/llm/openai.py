"""OpenAI-compatible Chat Completions client without an SDK dependency."""

from __future__ import annotations

import asyncio
import json
import os
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from typing import Any

from .client import LlmClientError
from .models import LlmResponse, ToolCall


class OpenAiCompatibleClient:
    """Small async adapter for OpenAI-compatible chat completion endpoints."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str,
        model: str,
        timeout: float = 60.0,
    ) -> None:
        self.base_url = base_url.strip()
        self.api_key = api_key
        self.model = model.strip()
        self.timeout = max(1.0, float(timeout))
        if not self.base_url:
            raise ValueError("LLM base_url is required")
        if not self.model:
            raise ValueError("LLM model is required")

    @classmethod
    def from_env(cls) -> "OpenAiCompatibleClient":
        raw_timeout = os.getenv("DEVICE_AI_TIMEOUT", "60")
        try:
            timeout = float(raw_timeout)
        except ValueError:
            timeout = 60.0
        return cls(
            base_url=os.getenv("DEVICE_AI_BASE_URL", "").strip() or "https://api.openai.com/v1",
            api_key=os.getenv("DEVICE_AI_API_KEY", ""),
            model=os.getenv("DEVICE_AI_MODEL", "").strip() or "gpt-4o-mini",
            timeout=timeout,
        )

    async def chat(
        self,
        *,
        messages: list[dict],
        tools: list[dict],
    ) -> LlmResponse:
        payload = {
            "model": self.model,
            "messages": messages,
            "tools": tools,
        }
        raw = await asyncio.to_thread(self._request, payload)
        return self._parse_response(raw)

    def _request(self, payload: dict[str, Any]) -> dict[str, Any]:
        endpoint = self.base_url.rstrip("/")
        if not endpoint.endswith("/chat/completions"):
            endpoint = f"{endpoint}/chat/completions"
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        request = Request(
            endpoint,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                body = response.read().decode("utf-8")
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            raise LlmClientError(f"LLM request failed ({exc.code}): {detail[:1_000]}") from exc
        except URLError as exc:
            raise LlmClientError(f"LLM request failed: {exc.reason}") from exc
        except TimeoutError as exc:
            raise LlmClientError("LLM request timed out") from exc
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError as exc:
            raise LlmClientError("LLM returned invalid JSON") from exc
        if not isinstance(parsed, dict):
            raise LlmClientError("LLM returned an invalid response object")
        return parsed

    @staticmethod
    def _parse_response(payload: dict[str, Any]) -> LlmResponse:
        choices = payload.get("choices")
        if not isinstance(choices, list) or not choices:
            error = payload.get("error")
            detail = error.get("message") if isinstance(error, dict) else "missing choices"
            raise LlmClientError(f"LLM response has no choices: {detail}")
        choice = choices[0]
        message = choice.get("message") if isinstance(choice, dict) else None
        if not isinstance(message, dict):
            raise LlmClientError("LLM response has no message")
        calls: list[ToolCall] = []
        raw_calls = message.get("tool_calls") or []
        if not isinstance(raw_calls, list):
            raise LlmClientError("LLM tool_calls must be a list")
        for index, raw_call in enumerate(raw_calls):
            if not isinstance(raw_call, dict):
                raise LlmClientError("LLM returned an invalid tool call")
            function = raw_call.get("function")
            if not isinstance(function, dict) or not function.get("name"):
                raise LlmClientError("LLM tool call is missing a function name")
            arguments = function.get("arguments") or "{}"
            if isinstance(arguments, str):
                try:
                    arguments = json.loads(arguments)
                except json.JSONDecodeError as exc:
                    raise LlmClientError("LLM tool arguments are invalid JSON") from exc
            if not isinstance(arguments, dict):
                raise LlmClientError("LLM tool arguments must be an object")
            calls.append(
                ToolCall(
                    id=str(raw_call.get("id") or f"tool-call-{index}"),
                    name=str(function["name"]),
                    arguments=dict(arguments),
                )
            )
        content = message.get("content")
        text = content if isinstance(content, str) else ""
        finish_reason = str(choice.get("finish_reason") or "") if isinstance(choice, dict) else ""
        return LlmResponse(text=text, tool_calls=calls, finish_reason=finish_reason)

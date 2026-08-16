"""Reusable request parameter validation."""

from __future__ import annotations

from typing import Any

from .core import AppControlError


class RequestValidationMixin:
    @staticmethod
    def _required_text(
        params: dict[str, Any],
        key: str,
        *,
        max_chars: int,
    ) -> str:
        value = str(params.get(key) or "").strip()
        if not value:
            raise AppControlError("invalid_request", f"缺少参数: {key}")
        if len(value) > max_chars:
            raise AppControlError(
                "input_too_large",
                f"参数 {key} 超过最大长度 {max_chars}。",
                status=413,
            )
        return value
    @staticmethod
    def _optional_text(
        params: dict[str, Any],
        key: str,
        *,
        max_chars: int,
    ) -> str:
        value = str(params.get(key) or "").strip()
        if len(value) > max_chars:
            raise AppControlError(
                "input_too_large",
                f"参数 {key} 超过最大长度 {max_chars}。",
                status=413,
            )
        return value
    @staticmethod
    def _choice(
        params: dict[str, Any],
        key: str,
        choices: set[str],
        *,
        default: str = "",
    ) -> str:
        value = str(params.get(key) or default).strip().casefold()
        if value not in choices:
            allowed = ", ".join(sorted(choices))
            raise AppControlError(
                "invalid_request",
                f"参数 {key} 必须是: {allowed}。",
            )
        return value
    @staticmethod
    def _integer(
        params: dict[str, Any],
        key: str,
        *,
        default: int,
        minimum: int,
        maximum: int,
    ) -> int:
        try:
            value = int(params.get(key, default))
        except (TypeError, ValueError) as exc:
            raise AppControlError("invalid_request", f"参数 {key} 必须是整数。") from exc
        if not minimum <= value <= maximum:
            raise AppControlError(
                "invalid_request",
                f"参数 {key} 必须在 {minimum} 到 {maximum} 之间。",
            )
        return value
    @staticmethod
    def _boolean(
        params: dict[str, Any],
        key: str,
        *,
        default: bool,
    ) -> bool:
        value = params.get(key, default)
        if not isinstance(value, bool):
            raise AppControlError(
                "invalid_request",
                f"参数 {key} 必须是布尔值。",
            )
        return value

"""Bind a node target without carrying another device's session identity."""

from __future__ import annotations

from typing import Any, Mapping


def device_id_value(value: Any) -> str:
    if isinstance(value, Mapping):
        value = value.get("device_id") or value.get("id")
    if not isinstance(value, str):
        raise ValueError("device must be an ID or an object with id/device_id")
    return value.strip()


def bind_device_target(context: Mapping[str, Any], device_id: str) -> dict[str, Any]:
    raw_target = context.get("target")
    target = dict(raw_target) if isinstance(raw_target, Mapping) else {}
    previous = str(target.get("device_id") or "")
    if previous and previous != device_id:
        for key in ("session_id", "protocol", "host", "port"):
            target.pop(key, None)
    target["device_id"] = device_id
    raw_device = context.get("device")
    device = dict(raw_device) if isinstance(raw_device, Mapping) and raw_device.get("id") == device_id else {"id": device_id}
    return {**context, "target": target, "device": device}

"""Huawei VRP adapter for framework Workflow discovery and output events."""

from __future__ import annotations

import re

from device_tui.framework.events import Event


class HuaweiVrpWorkflowAdapter:
    """Expose Huawei capabilities and translate terminal output to events."""

    id = "huawei-vrp"

    def matches(self, facts: dict[str, object]) -> bool:
        identity = " ".join(str(facts.get(key, "")) for key in ("vendor", "model", "platform")).casefold()
        return "huawei" in identity or "vrp" in identity

    def capabilities(self) -> set[str]:
        return {"huawei.vrp", "file.transfer", "device.reboot", "huawei.startup"}

    def parse_output(self, output: str, *, run_id: str, action_id: str) -> tuple[Event, ...]:
        events: list[Event] = []
        patterns = (
            (r"(?im)^\s*(?:ftp>|\[ftp\])\s*$", "huawei.ftp.ready", False),
            (r"(?i)(?:transfer|download).{0,80}(?:start|begin)", "huawei.transfer.started", True),
            (r"(?i)(?:transfer|download).{0,80}(?:complete|success|finished)", "huawei.transfer.completed", True),
            (r"(?i)startup.{0,80}(?:success|configured|saved)", "huawei.startup.configured", False),
            (r"(?i)(?:reboot|restart).{0,80}(?:start|system is rebooting)", "huawei.reboot.started", False),
            (r"(?i)(?:version|software).{0,100}(?:match|expected)", "huawei.version.match", False),
        )
        for pattern, event_type, progress in patterns:
            if re.search(pattern, output):
                events.append(Event(type=event_type, run_id=run_id, action_id=action_id, source="huawei.parser", progress=progress))
        return tuple(events)


__all__ = ["HuaweiVrpWorkflowAdapter"]

"""Framework for AI-assisted device operations with risk gates."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
import re
from typing import Any, Protocol


class RiskLevel(IntEnum):
    OBSERVE = 0
    LOW = 1
    MEDIUM = 2
    HIGH = 3
    FLOW = 4


READ_ONLY_COMMANDS = (
    "display",
    "dir",
    "ping",
    "screen-length",
    "show",
)
MEDIUM_RISK_COMMANDS = (
    "copy",
    "ftp",
    "get",
    "put",
    "sftp",
    "system-view",
    "telnet",
)
HIGH_RISK_COMMAND_PATTERNS = (
    r"\bdelete\b",
    r"\berase\b",
    r"\bformat\b",
    r"\breboot\b",
    r"\breset\b",
    r"\bsave\b",
    r"\bstartup\s+system-software\b",
    r"\bpower\s*off\b",
    r"\bshutdown\b",
    r"\bundo\b",
)


@dataclass(slots=True)
class DeviceSnapshot:
    id: str
    name: str
    status: str = ""
    domain: str = ""
    kind: str = ""
    selected: bool = False


@dataclass(slots=True)
class AiDeviceAction:
    kind: str
    label: str
    risk: RiskLevel
    device_id: str = ""
    command: str = ""
    params: dict[str, Any] = field(default_factory=dict)

    @property
    def requires_confirmation(self) -> bool:
        return self.risk >= RiskLevel.MEDIUM


@dataclass(slots=True)
class AiDevicePlan:
    objective: str
    summary: str
    actions: list[AiDeviceAction]
    warnings: list[str] = field(default_factory=list)

    @property
    def requires_confirmation(self) -> bool:
        return any(action.requires_confirmation for action in self.actions)


@dataclass(slots=True)
class AiDeviceToolResult:
    action: AiDeviceAction
    ok: bool
    message: str
    data: dict[str, Any] = field(default_factory=dict)
    approval_required: bool = False
    error_code: str = ""
    http_status: int = 409


class AiDeviceOpsBackend(Protocol):
    def list_device_snapshots(self) -> list[DeviceSnapshot]:
        ...

    def selected_device_id(self) -> str:
        ...

    def execute_ai_device_action(
        self,
        action: AiDeviceAction,
        *,
        approved: bool = False,
    ) -> AiDeviceToolResult:
        ...


def classify_command_risk(command: str) -> RiskLevel:
    normalized = " ".join(command.strip().split()).casefold()
    if not normalized:
        return RiskLevel.OBSERVE
    for pattern in HIGH_RISK_COMMAND_PATTERNS:
        if re.search(pattern, normalized):
            return RiskLevel.HIGH
    first = normalized.split(maxsplit=1)[0]
    if first in MEDIUM_RISK_COMMANDS:
        return RiskLevel.MEDIUM
    if first in READ_ONLY_COMMANDS:
        return RiskLevel.LOW
    if normalized.startswith("sim upgrade "):
        return RiskLevel.LOW
    return RiskLevel.MEDIUM


def find_simulated_device_id(devices: list[DeviceSnapshot]) -> str:
    for device in devices:
        haystack = f"{device.id} {device.name} {device.kind} {device.domain}".casefold()
        if "sim" in haystack or "模拟" in haystack:
            return device.id
    return ""


class SimpleAiDevicePlanner:
    """Small deterministic planner used until a model is connected."""

    def build_plan(
        self,
        objective: str,
        devices: list[DeviceSnapshot],
        *,
        selected_device_id: str = "",
    ) -> AiDevicePlan:
        normalized = objective.casefold()
        device_id = find_simulated_device_id(devices) if "模拟" in objective or "sim" in normalized else selected_device_id
        actions: list[AiDeviceAction] = []
        warnings: list[str] = []

        if any(keyword in objective for keyword in ("换包", "大包", "升级")):
            if not device_id:
                warnings.append("未找到可操作设备，需要先选择设备。")
            actions.extend(self._failure_toggle_actions(objective, device_id))
            actions.extend([
                AiDeviceAction("select_device", "选择目标设备", RiskLevel.OBSERVE, device_id=device_id),
                AiDeviceAction("open_session", "打开终端会话", RiskLevel.LOW, device_id=device_id),
                AiDeviceAction("run_package_upgrade", "执行受控自动换包流程", RiskLevel.FLOW, device_id=device_id),
            ])
            return AiDevicePlan(
                objective=objective,
                summary="通过受控换包状态机执行，危险命令由流程层校验和确认。",
                actions=actions,
                warnings=warnings,
            )

        if "版本" in objective or "version" in normalized:
            if not device_id:
                warnings.append("未找到可操作设备，需要先选择设备。")
            actions.extend([
                AiDeviceAction("select_device", "选择目标设备", RiskLevel.OBSERVE, device_id=device_id),
                AiDeviceAction("open_session", "打开终端会话", RiskLevel.LOW, device_id=device_id),
                AiDeviceAction(
                    "send_command",
                    "查看设备版本",
                    classify_command_risk("display version"),
                    device_id=device_id,
                    command="display version",
                ),
                AiDeviceAction("read_terminal", "读取终端输出", RiskLevel.OBSERVE, device_id=device_id),
            ])
            return AiDevicePlan(
                objective=objective,
                summary="读取设备版本信息，不涉及配置变更。",
                actions=actions,
                warnings=warnings,
            )

        return AiDevicePlan(
            objective=objective,
            summary="当前框架尚未识别该意图，只生成观察计划。",
            actions=[
                AiDeviceAction("list_devices", "读取设备列表", RiskLevel.OBSERVE),
            ],
            warnings=["需要接入模型或补充规则后再自动规划该意图。"],
        )

    def _failure_toggle_actions(self, objective: str, device_id: str) -> list[AiDeviceAction]:
        toggles = {
            "下载失败": "sim upgrade fail-download on",
            "空间不足": "sim upgrade fail-space on",
            "启动项失败": "sim upgrade fail-startup on",
        }
        return [
            AiDeviceAction(
                "send_command",
                f"开启模拟场景: {label}",
                classify_command_risk(command),
                device_id=device_id,
                command=command,
            )
            for label, command in toggles.items()
            if label in objective
        ]

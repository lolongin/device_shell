from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Mapping

@dataclass(frozen=True, slots=True)
class ActionSpec:
    id: str
    name: str
    category: str
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)
    risk: str = "low"
    executor_id: str = ""

    @property
    def required_inputs(self) -> tuple[str, ...]:
        return tuple(self.input_schema.get("required", ()))

class ActionCatalog:
    def __init__(self, actions: tuple[ActionSpec, ...] = ()) -> None:
        self._actions = {a.id: a for a in actions}
    def register(self, action: ActionSpec) -> None: self._actions[action.id] = action
    def get(self, action_id: str) -> ActionSpec | None: return self._actions.get(action_id)
    def list(self) -> tuple[ActionSpec, ...]: return tuple(self._actions.values())

def build_action_catalog() -> ActionCatalog:
    def a(id: str, name: str, category: str, required: tuple[str, ...] = (), risk: str = "low", **props: Any) -> ActionSpec:
        return ActionSpec(id, name, category, {"type": "object", "properties": props, "required": list(required)}, {}, risk, id)
    return ActionCatalog(tuple([
        a("device.select", "选择设备", "device", ("device_id",), device_id={"type": "string"}),
        a("device.ssh", "SSH 连接", "connection", ("host",), host={"type": "string"}, port={"type": "integer"}),
        a("device.telnet", "Telnet 连接", "connection", ("host",), host={"type": "string"}, port={"type": "integer"}),
        a("device.command", "执行命令", "device", ("command",), command={"type": "string"}),
        a("file.upload", "上传文件", "transfer", ("source", "destination"), source={"type": "string"}, destination={"type": "string"}, risk="high"),
        a("file.download", "下载文件", "transfer", ("source", "destination"), source={"type": "string"}, destination={"type": "string"}),
        a("device.reboot", "重启设备", "device", risk="high"),
        a("utility.wait", "等待", "control", ("seconds",), seconds={"type": "number"}),
        a("utility.condition", "条件判断", "control", ("expression",), expression={"type": "string"}),
    ]))

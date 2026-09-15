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
    def output(**props: Any) -> dict[str, Any]:
        return {"type": "object", "properties": props}

    def a(
        id: str,
        display_name: str,
        category: str,
        required: tuple[str, ...] = (),
        risk: str = "low",
        outputs: dict[str, Any] | None = None,
        **props: Any,
    ) -> ActionSpec:
        return ActionSpec(
            id,
            display_name,
            category,
            {"type": "object", "properties": props, "required": list(required)},
            outputs or {},
            risk,
            id,
        )

    execution_outputs = output(
        output={"type": "string"},
        status={"type": "string"},
        execution_id={"type": "string"},
        operation_id={"type": "string"},
        session_id={"type": "string"},
        host={"type": "string"},
        port={"type": "integer"},
        device_id={"type": "string"},
        cli_status={"type": "string"},
        evidence={"type": "array"},
    )
    transfer_outputs = output(
        status={"type": "string"},
        operation_id={"type": "string"},
        verified={"type": "boolean"},
        skipped={"type": "boolean"},
        skip_reason={"type": "string"},
        output={"type": "string"},
        evidence={"type": "array"},
    )
    return ActionCatalog(tuple([
        a("device.select", "选择设备", "device", ("device_id",), outputs=output(device_id={"type": "string"}, status={"type": "string"}), device_id={"type": "string"}),
        a("device.connect", "连接设备", "device", (), outputs=execution_outputs, device_id={"type": "string"}, timeout_seconds={"type": "number"}),
        a(
            "device.info",
            "获取设备信息",
            "device",
            (),
            outputs=output(
                name={"type": "string"},
                address={"type": "string"},
                model={"type": "string"},
                version={"type": "string"},
                **execution_outputs["properties"],
                software_version={"type": "string"},
                requested_fields={"type": "array"},
            ),
            fields={"type": "array"},
        ),
        a("device.ssh", "SSH 连接", "connection", (), outputs=execution_outputs, host={"type": "string"}, port={"type": "integer"}),
        a("device.telnet", "Telnet 连接", "connection", (), outputs=execution_outputs, host={"type": "string"}, port={"type": "integer"}),
        a("device.command", "执行命令", "device", ("command",), outputs=execution_outputs, command={"type": "string"}),
        a("file.upload", "上传文件", "transfer", ("source", "destination"), source={"type": "string"}, destination={"type": "string"}, outputs=transfer_outputs, risk="high"),
        a("file.download", "下载文件", "transfer", ("source", "destination"), source={"type": "string"}, destination={"type": "string"}, outputs=transfer_outputs),
        a("device.reboot", "重启设备", "device", outputs=execution_outputs, risk="high"),
        a("utility.wait", "等待", "control", ("seconds",), outputs=output(seconds={"type": "number"}, status={"type": "string"}), seconds={"type": "number"}),
        a("terminal.wait", "等待终端输出", "control", ("pattern",), outputs=output(status={"type": "string"}, matched={"type": "boolean"}, output={"type": "string"}, sequence={"type": "integer"}, session_id={"type": "string"}), mode={"type": "string", "enum": ["contains", "regex"]}, pattern={"type": "string"}, case_sensitive={"type": "boolean"}, send_enter={"type": "boolean"}, timeout_seconds={"type": "number"}, after_sequence={"type": "integer"}),
        a("utility.condition", "条件判断", "control", (), expression={"type": "string"}, rules={"type": "array"}, logical_operator={"type": "string"}),
        a("utility.confirm", "人工确认", "control", ("prompt",), outputs=output(approved={"type": "boolean"}, option_id={"type": "string"}, reason={"type": "string"}, status={"type": "string"}), prompt={"type": "string"}, approve_label={"type": "string"}, reject_label={"type": "string"}),
        a("result.save", "保存结果", "result", (), outputs=output(status={"type": "string"}, key={"type": "string"}, value={}), key={"type": "string"}),
        a(
            "variable.set",
            "设置变量",
            "control",
            ("name",),
            outputs=output(name={"type": "string"}, value={}, matched={"type": "boolean"}, source={}),
            name={"type": "string"},
            value={"type": ["string", "number", "boolean", "object", "array", "null"]},
            extract={
                "type": "object",
                "properties": {
                    "pattern": {"type": "string"},
                    "group": {"type": "integer", "minimum": 0},
                    "mode": {"type": "string", "enum": ["match", "line"]},
                },
            },
        ),
        a("expression.evaluate", "计算表达式", "control", ("expression",), outputs=output(value={}, status={"type": "string"}), expression={"type": "string"}, values={"type": "object"}),
        a("loop.for_each", "循环 FOR", "control", ("items", "action_id"), outputs=output(items={"type": "array"}, results={"type": "array"}, count={"type": "integer"}), items={"type": "array"}, action_id={"type": "string"}, action_inputs={"type": "object"}),
        a("loop.until", "循环直到满足", "control", ("action_id", "condition"), outputs=output(status={"type": "string"}, matched={"type": "boolean"}, iterations={"type": "integer"}, result={"type": "object"}, results={"type": "array"}), action_id={"type": "string"}, action_inputs={"type": "object"}, condition={"type": "string"}, max_iterations={"type": "integer"}, interval_seconds={"type": "number"}),
    ]))

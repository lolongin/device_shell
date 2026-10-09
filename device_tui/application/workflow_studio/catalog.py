from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Mapping

from device_tui.application.workflow_runtime.output_contract import COMMAND_OUTPUT_SCHEMA

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

    def input_binding(raw: Any, mode: str = "runtime", reference_types: tuple[str, ...] = ()) -> Any:
        """Attach the shared runtime binding contract to an input schema."""
        if not isinstance(raw, Mapping):
            return raw
        result = dict(raw)
        existing_binding = result.get("binding") if isinstance(result.get("binding"), Mapping) else {}
        if mode == "static":
            result["binding"] = {"mode": "static"}
        else:
            types = reference_types
            if not types:
                raw_reference_types = existing_binding.get("reference_types")
                if isinstance(raw_reference_types, (list, tuple)):
                    types = tuple(str(item) for item in raw_reference_types)
            if not types:
                raw_type = result.get("type")
                candidates = raw_type if isinstance(raw_type, list) else [raw_type]
                types = tuple(
                    {
                        "string": "string",
                        "file": "file",
                        "device": "device",
                        "number": "number",
                        "integer": "integer",
                        "boolean": "boolean",
                        "array": "array",
                        "devices": "devices",
                        "object": "object",
                    }.get(str(item), str(item))
                    for item in candidates
                    if item not in (None, "null")
                )
                if mode == "template" and types == ("string",):
                    types = ("string", "file", "device", "number", "integer", "boolean")
            result["binding"] = {"mode": mode, "reference_types": list(types)}
        return result

    def a(
        id: str,
        display_name: str,
        category: str,
        required: tuple[str, ...] = (),
        risk: str = "low",
        outputs: dict[str, Any] | None = None,
        runtime_fields: tuple[str, ...] = (),
        template_fields: tuple[str, ...] = (),
        static_fields: tuple[str, ...] = (),
        **props: Any,
    ) -> ActionSpec:
        runtime = set(runtime_fields)
        templates = set(template_fields)
        static = set(static_fields)
        normalized_props = {
            name: input_binding(
                value,
                (
                    "static"
                    if name in static
                    else "template"
                    if name in templates
                    else "runtime"
                    if name in runtime
                    else str(value.get("binding", {}).get("mode") or "static")
                    if isinstance(value, Mapping) and isinstance(value.get("binding"), Mapping)
                    else "static"
                ),
            )
            for name, value in props.items()
        }
        public_outputs = dict(outputs or {})
        primary_fields = {
            "device.connect": ("execution_status", "device_id", "session_id", "cli_status", "error"),
            "device.ssh": ("execution_status", "device_id", "session_id", "host", "port", "error"),
            "device.telnet": ("execution_status", "device_id", "session_id", "host", "port", "error"),
            "device.info": ("execution_status", "device_id", "name", "address", "model", "software_version", "device_status", "output"),
            "device.reboot": ("execution_status", "operation_id", "device_id", "output", "error"),
            "device.command": ("output", "stderr", "exit_code", "execution_status", "error"),
        }.get(id)
        if primary_fields:
            public_outputs["primary_fields"] = list(primary_fields)
        return ActionSpec(
            id,
            display_name,
            category,
            {"type": "object", "properties": normalized_props, "required": list(required)},
            public_outputs,
            risk,
            id,
        )

    execution_outputs = output(
        **COMMAND_OUTPUT_SCHEMA["properties"],
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
        stage={"type": "string"},
        progress_percent={"type": "number"},
        bytes_transferred={"type": "integer"},
        total_bytes={"type": "integer"},
        source_path={"type": "string"},
        destination_path={"type": "string"},
        data={"type": "object", "additionalProperties": True},
    )
    return ActionCatalog(tuple([
        a("device.select", "选择设备", "device", ("device_id",), outputs=output(device_id={"type": "string"}, status={"type": "string"}), runtime_fields=("device_id",), device_id={"type": ["string", "object"]}),
        a("device.connect", "连接设备", "device", (), outputs=execution_outputs, runtime_fields=("device_id", "timeout_seconds"), device_id={"type": ["string", "object"]}, timeout_seconds={"type": "number"}),
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
                device_status={"type": "string"},
            ),
            static_fields=("fields",),
            runtime_fields=("timeout_seconds", "session_id"),
            timeout_seconds={"type": "number"},
            session_id={"type": "string"},
            fields={"type": "array", "items": {"type": "string"}, "deprecated": True},
        ),
        a("device.ssh", "SSH 连接", "connection", (), outputs=execution_outputs, runtime_fields=("host", "port"), host={"type": "string"}, port={"type": "integer"}),
        a("device.telnet", "Telnet 连接", "connection", (), outputs=execution_outputs, runtime_fields=("host", "port"), host={"type": "string"}, port={"type": "integer"}),
        a(
            "device.command",
            "执行命令",
            "device",
            ("command",),
            outputs=execution_outputs,
            template_fields=("command",),
            runtime_fields=("timeout_seconds", "cwd", "env"),
            command={"type": "string"},
            execution_mode={"type": "string", "enum": ["device", "shell", "bash"]},
            timeout_seconds={"type": "number"},
            cwd={"type": "string"},
            env={"type": "object"},
            retry_attempts={"type": "integer"},
            retry_backoff_seconds={"type": "number"},
            failure_strategy={"type": "string", "enum": ["stop", "continue"]},
        ),
        a(
            "script.run",
            "执行脚本",
            "script",
            ("script",),
            outputs=output(
                output={"type": "string"},
                stdout={"type": "string"},
                stderr={"type": "string"},
                returncode={"type": ["integer", "null"], "deprecated": True},
                exit_code={"type": ["integer", "null"]},
                exitCode={"type": ["integer", "null"], "deprecated": True},
                status={"type": "string"},
                result={},
                result_parsed={"type": "boolean"},
            ),
            runtime_fields=("input_json", "cwd", "env", "timeout_seconds", "max_output_chars"),
            language={"type": "string", "enum": ["python", "powershell", "bash"]},
            script={"type": "string"},
            input_json={"type": ["string", "object", "array", "number", "boolean", "null"]},
            cwd={"type": "string"},
            env={"type": "object"},
            timeout_seconds={"type": "number"},
            max_output_chars={"type": "integer"},
            retry_attempts={"type": "integer"},
            retry_backoff_seconds={"type": "number"},
            risk="high",
        ),
        a(
            "file.upload", "上传文件", "transfer", ("source",),
            runtime_fields=("source", "destination", "overwrite"),
            source={"type": "string", "description": "本机文件绝对路径；可通过选择文件填写"},
            destination={"type": "string", "description": "设备目标路径；VRP 设备留空默认 flash:/文件名"},
            overwrite={"type": "boolean", "default": True, "description": "目标文件已存在时覆盖"},
            outputs=transfer_outputs, risk="high",
        ),
        a(
            "file.download", "下载文件", "transfer", ("source", "destination"),
            runtime_fields=("source", "destination"),
            source={"type": "string", "description": "设备源文件路径"},
            destination={"type": "string", "description": "本机保存路径"},
            outputs=transfer_outputs,
        ),
        a("device.reboot", "重启设备", "device", outputs=execution_outputs, risk="high"),
        a("utility.wait", "等待", "control", ("seconds",), outputs=output(seconds={"type": "number"}, status={"type": "string"}), runtime_fields=("seconds",), seconds={"type": "number"}),
        a("terminal.wait", "等待终端输出", "control", ("pattern",), outputs=output(status={"type": "string"}, matched={"type": "boolean"}, output={"type": "string"}, sequence={"type": "integer"}, session_id={"type": "string"}), template_fields=("pattern",), runtime_fields=("mode", "case_sensitive", "send_enter", "timeout_seconds", "after_sequence", "session_id", "device_id"), mode={"type": "string", "enum": ["contains", "regex"]}, pattern={"type": "string"}, case_sensitive={"type": "boolean"}, send_enter={"type": "boolean", "default": False}, timeout_seconds={"type": "number"}, after_sequence={"type": "integer"}, session_id={"type": "string"}, device_id={"type": "string"}),
        a(
            "utility.condition",
            "条件判断",
            "control",
            (),
            static_fields=("logical_operator",),
            template_fields=(),
            expression={"type": "string", "binding": {"mode": "expression", "reference_types": ["string", "number", "integer", "boolean", "object", "array"]}},
            rules={
                "type": "array",
                "binding": {"mode": "json"},
                "items": {
                    "type": "object",
                    "properties": {
                        "field": {"type": "string", "binding": {"mode": "runtime", "reference_types": ["string", "number", "integer", "boolean", "object"]}},
                        "value": {"type": ["string", "number", "integer", "boolean", "null"], "binding": {"mode": "runtime", "reference_types": ["string", "number", "integer", "boolean", "object", "array"]}},
                        "operator": {"type": "string", "binding": {"mode": "static"}},
                    },
                },
            },
            logical_operator={"type": "string", "enum": ["AND", "OR"]},
        ),
        a("utility.confirm", "人工确认", "control", ("prompt",), outputs=output(approved={"type": "boolean"}, option_id={"type": "string"}, reason={"type": "string"}, status={"type": "string"}), template_fields=("prompt", "approve_label", "reject_label"), prompt={"type": "string"}, approve_label={"type": "string"}, reject_label={"type": "string"}),
        a("result.save", "保存结果", "result", (), outputs=output(status={"type": "string"}, key={"type": "string"}, value={}), static_fields=("key",), runtime_fields=("value",), key={"type": "string", "description": "可选；留空时使用节点 ID"}, value={"type": ["string", "number", "boolean", "object", "array", "null"]}),
        a(
            "variable.set",
            "设置变量",
            "control",
            ("name",),
            outputs=output(name={"type": "string"}, value={}, matched={"type": "boolean"}, source={}),
            runtime_fields=("value", "extract"),
            static_fields=("name",),
            name={"type": "string"},
            value={"type": ["string", "number", "boolean", "object", "array", "null"]},
            extract={
                "type": "object",
                "properties": {
                    "pattern": {"type": "string"},
                    "group": {"type": "integer", "minimum": 0},
                    "mode": {"type": "string", "enum": ["match", "line"]},
                    "convert": {"type": "string", "enum": ["string", "integer", "number", "boolean", "json"]},
                    "trim": {"type": "boolean"},
                },
            },
        ),
        a("expression.evaluate", "计算表达式", "control", ("expression",), outputs=output(value={}, status={"type": "string"}), runtime_fields=("values",), expression={"type": "string", "binding": {"mode": "expression", "reference_types": ["string", "number", "integer", "boolean", "object", "array"]}}, values={"type": "object", "binding": {"mode": "json"}}),
        a("loop.for_each", "循环 FOR", "control", ("items", "action_id"), outputs=output(items={"type": "array", "items": {}}, results={"type": "array", "items": {"type": "object"}}, count={"type": "integer"}, status={"type": "string"}), runtime_fields=("items", "action_inputs"), static_fields=("action_id",), items={"type": "array", "items": {}}, action_id={"type": "string"}, action_inputs={"type": "object"}),
        a("device.for_each", "遍历设备", "device", ("devices",), outputs=output(devices={"type": "array", "items": {"type": "string"}}, results={"type": "array", "items": {"type": "object"}}, count={"type": "integer"}, succeeded={"type": "integer"}, failed={"type": "integer"}, status={"type": "string"}), runtime_fields=("devices", "action_inputs", "concurrency"), static_fields=("body_mode", "body_start", "body_end", "action_id", "failure_strategy"), devices={"type": "array", "items": {"type": "string"}}, body_mode={"type": "string", "enum": ["downstream", "bounded", "action"]}, body_start={"type": "string"}, body_end={"type": "string"}, action_id={"type": "string"}, action_inputs={"type": "object"}, concurrency={"type": "integer", "minimum": 1, "maximum": 32, "default": 1}, failure_strategy={"type": "string", "enum": ["stop", "continue"]}),
        a("loop.until", "循环直到满足", "control", ("action_id", "condition"), outputs=output(status={"type": "string"}, matched={"type": "boolean"}, iterations={"type": "integer"}, result={"type": "object"}, results={"type": "array", "items": {"type": "object"}}), template_fields=("condition",), runtime_fields=("action_inputs", "max_iterations", "interval_seconds"), static_fields=("action_id",), action_id={"type": "string"}, action_inputs={"type": "object"}, condition={"type": "string"}, max_iterations={"type": "integer"}, interval_seconds={"type": "number"}),
        a(
            "workflow.call",
            "调用子流程",
            "workflow",
            ("workflow_id", "version"),
            outputs=output(
                status={"type": "string"},
                workflow_id={"type": "string"},
                version={"type": "integer"},
                outputs={"type": "object"},
            ),
            static_fields=("workflow_id", "version"),
            runtime_fields=("inputs",),
            workflow_id={"type": "string"},
            version={"type": "integer"},
            inputs={"type": "object"},
        ),
    ]))

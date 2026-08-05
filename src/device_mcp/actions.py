"""Public tool input to guarded action conversion."""

from __future__ import annotations

from typing import Any

from ..ai_device_ops import AiDeviceAction, RiskLevel, classify_command_risk
from ..terminal_orchestration import TerminalPlanError, build_batch_plan, parse_terminal_plan
from .core import (
    DEFAULT_OUTPUT_CHARS,
    MAX_COMMAND_CHARS,
    MAX_OUTPUT_CHARS,
    SESSION_ACTIONS,
    SESSION_PROTOCOLS,
    TERMINAL_PLAN_MODES,
    AppControlError,
    normalize_command,
)


class ActionBuilderMixin:
    def _build_action(self, tool: str, params: dict[str, Any]) -> AiDeviceAction:
        if tool == "system_status":
            return AiDeviceAction(
                "system_status",
                "读取 Device TUI 运行状态",
                RiskLevel.OBSERVE,
            )
        if tool == "device_list":
            return AiDeviceAction("list_devices", "读取设备列表", RiskLevel.OBSERVE)
        if tool == "file_transfer_list":
            recursive = self._boolean(
                params,
                "recursive",
                default=True,
            )
            limit = self._integer(
                params,
                "limit",
                default=200,
                minimum=1,
                maximum=1_000,
            )
            return AiDeviceAction(
                "list_managed_transfer_files",
                "列出文件传输共享目录",
                RiskLevel.OBSERVE,
                params={
                    "path": self._optional_text(params, "path", max_chars=1_024),
                    "recursive": recursive,
                    "limit": limit,
                },
            )
        if tool == "session_list":
            device_id = self._optional_text(params, "device_id", max_chars=200)
            return AiDeviceAction(
                "session_list",
                "读取终端会话列表",
                RiskLevel.OBSERVE,
                device_id=device_id,
                params={"device_id": device_id},
            )
        if tool == "session_manage":
            operation = self._choice(params, "action", SESSION_ACTIONS)
            protocol = self._choice(
                params,
                "protocol",
                SESSION_PROTOCOLS,
                default="auto",
            )
            device_id = self._optional_text(params, "device_id", max_chars=200)
            session_id = self._optional_text(params, "session_id", max_chars=240)
            if operation == "open" and not device_id:
                raise AppControlError(
                    "invalid_request",
                    "打开会话需要 device_id。",
                )
            if operation != "open" and not session_id and not device_id:
                raise AppControlError(
                    "invalid_request",
                    "会话操作需要 session_id 或 device_id。",
                )
            timeout_seconds = self._integer(
                params,
                "timeout_seconds",
                default=15,
                minimum=1,
                maximum=60,
            )
            return AiDeviceAction(
                "session_manage",
                f"管理终端会话: {operation}",
                RiskLevel.LOW,
                device_id=device_id,
                params={
                    "action": operation,
                    "protocol": protocol,
                    "session_id": session_id,
                    "timeout_seconds": timeout_seconds,
                },
            )
        if tool == "terminal_run":
            raw_commands = params.get("commands")
            if not isinstance(raw_commands, list):
                raise AppControlError("invalid_request", "参数 commands 必须是数组。")
            commands = [normalize_command(str(command)) for command in raw_commands]
            command_timeout_seconds = self._integer(
                params,
                "command_timeout_seconds",
                default=30,
                minimum=1,
                maximum=300,
            )
            max_output_chars = self._integer(
                params,
                "max_output_chars_per_step",
                default=16_384,
                minimum=1,
                maximum=MAX_OUTPUT_CHARS,
            )
            requested_total = params.get("total_timeout_seconds")
            total_timeout_seconds = (
                self._integer(
                    params,
                    "total_timeout_seconds",
                    default=60,
                    minimum=1,
                    maximum=3600,
                )
                if requested_total is not None
                else None
            )
            try:
                plan = build_batch_plan(
                    commands,
                    command_timeout_seconds=command_timeout_seconds,
                    total_timeout_seconds=total_timeout_seconds,
                    max_output_chars=max_output_chars,
                )
            except TerminalPlanError as exc:
                raise AppControlError(exc.code, str(exc)) from exc
            device_id, session_id = self._terminal_target(params)
            protocol = self._choice(
                params,
                "protocol",
                SESSION_PROTOCOLS,
                default="auto",
            )
            ensure_session = self._boolean(
                params,
                "ensure_session",
                default=True,
            )
            risk = max(
                (classify_command_risk(command) for command in commands),
                default=RiskLevel.LOW,
            )
            run_async = self._terminal_plan_runs_async(
                "auto",
                plan.total_timeout_seconds,
                has_state_wait=False,
            )
            return AiDeviceAction(
                "terminal_run",
                "准备会话并执行终端命令",
                risk,
                device_id=device_id,
                params={
                    "plan_kind": "batch",
                    "commands": commands,
                    "session_id": session_id,
                    "ensure_session": ensure_session,
                    "protocol": protocol,
                    "command_timeout_seconds": command_timeout_seconds,
                    "total_timeout_seconds": plan.total_timeout_seconds,
                    "max_output_chars_per_step": max_output_chars,
                    "mode": "auto",
                    "run_async": run_async,
                },
            )
        if tool == "terminal_execute":
            command = self._required_text(
                params,
                "command",
                max_chars=MAX_COMMAND_CHARS,
            )
            normalized = normalize_command(command)
            device_id = self._optional_text(params, "device_id", max_chars=200)
            session_id = self._optional_text(params, "session_id", max_chars=240)
            if not device_id and not session_id:
                raise AppControlError(
                    "invalid_request",
                    "执行命令需要 session_id 或 device_id。",
                )
            timeout_seconds = self._integer(
                params,
                "timeout_seconds",
                default=30,
                minimum=1,
                maximum=300,
            )
            max_output_chars = self._integer(
                params,
                "max_output_chars",
                default=16_384,
                minimum=1,
                maximum=MAX_OUTPUT_CHARS,
            )
            return AiDeviceAction(
                "terminal_execute_start",
                "执行终端命令并等待结果",
                classify_command_risk(normalized),
                device_id=device_id,
                command=normalized,
                params={
                    "session_id": session_id,
                    "timeout_seconds": timeout_seconds,
                    "max_output_chars": max_output_chars,
                },
            )
        if tool == "terminal_execute_batch":
            raw_commands = params.get("commands")
            if not isinstance(raw_commands, list):
                raise AppControlError("invalid_request", "参数 commands 必须是数组。")
            commands = [normalize_command(str(command)) for command in raw_commands]
            command_timeout_seconds = self._integer(
                params,
                "command_timeout_seconds",
                default=30,
                minimum=1,
                maximum=300,
            )
            max_output_chars = self._integer(
                params,
                "max_output_chars_per_step",
                default=16_384,
                minimum=1,
                maximum=MAX_OUTPUT_CHARS,
            )
            requested_total = params.get("total_timeout_seconds")
            total_timeout_seconds = (
                self._integer(
                    params,
                    "total_timeout_seconds",
                    default=60,
                    minimum=1,
                    maximum=3600,
                )
                if requested_total is not None
                else None
            )
            try:
                plan = build_batch_plan(
                    commands,
                    command_timeout_seconds=command_timeout_seconds,
                    total_timeout_seconds=total_timeout_seconds,
                    max_output_chars=max_output_chars,
                )
            except TerminalPlanError as exc:
                raise AppControlError(exc.code, str(exc)) from exc
            mode = self._choice(
                params,
                "mode",
                TERMINAL_PLAN_MODES,
                default="auto",
            )
            run_async = self._terminal_plan_runs_async(
                mode,
                plan.total_timeout_seconds,
                has_state_wait=False,
            )
            device_id, session_id = self._terminal_target(params)
            risk = max(
                (classify_command_risk(command) for command in commands),
                default=RiskLevel.LOW,
            )
            return AiDeviceAction(
                "terminal_plan_start",
                "批量执行终端命令",
                risk,
                device_id=device_id,
                params={
                    "plan_kind": "batch",
                    "commands": commands,
                    "session_id": session_id,
                    "command_timeout_seconds": command_timeout_seconds,
                    "total_timeout_seconds": plan.total_timeout_seconds,
                    "max_output_chars_per_step": max_output_chars,
                    "mode": mode,
                    "run_async": run_async,
                },
            )
        if tool == "terminal_interact":
            raw_steps = params.get("steps")
            if not isinstance(raw_steps, list):
                raise AppControlError("invalid_request", "参数 steps 必须是数组。")
            total_timeout_seconds = self._integer(
                params,
                "total_timeout_seconds",
                default=60,
                minimum=1,
                maximum=3600,
            )
            try:
                plan = parse_terminal_plan(
                    raw_steps,
                    total_timeout_seconds=total_timeout_seconds,
                )
            except TerminalPlanError as exc:
                raise AppControlError(exc.code, str(exc)) from exc
            mode = self._choice(
                params,
                "mode",
                TERMINAL_PLAN_MODES,
                default="auto",
            )
            has_state_wait = any(
                str(step.get("type") or "").casefold() == "wait_state"
                for step in raw_steps
                if isinstance(step, dict)
            )
            run_async = self._terminal_plan_runs_async(
                mode,
                plan.total_timeout_seconds,
                has_state_wait=has_state_wait,
            )
            device_id, session_id = self._terminal_target(params)
            risk = RiskLevel.FLOW
            for step in raw_steps:
                if not isinstance(step, dict):
                    continue
                texts = [str(step.get("text") or "")]
                responses = step.get("responses")
                if isinstance(responses, list):
                    texts.extend(
                        str(response.get("text") or "")
                        for response in responses
                        if isinstance(response, dict)
                    )
                for text in texts:
                    if text:
                        risk = max(risk, classify_command_risk(text))
            return AiDeviceAction(
                "terminal_plan_start",
                "执行交互式终端计划",
                risk,
                device_id=device_id,
                params={
                    "plan_kind": "interactive",
                    "steps": raw_steps,
                    "session_id": session_id,
                    "total_timeout_seconds": plan.total_timeout_seconds,
                    "mode": mode,
                    "run_async": run_async,
                },
            )
        if tool in {"execution_get", "execution_cancel"}:
            execution_id = self._required_text(
                params,
                "execution_id",
                max_chars=80,
            )
            return AiDeviceAction(
                "terminal_execution_get"
                if tool == "execution_get"
                else "terminal_execution_cancel",
                "读取终端执行状态"
                if tool == "execution_get"
                else "取消终端执行",
                RiskLevel.OBSERVE if tool == "execution_get" else RiskLevel.LOW,
                params={"execution_id": execution_id},
            )
        if tool == "ai_create_session":
            return AiDeviceAction(
                "ai_gateway_create_session",
                "创建网关会话",
                RiskLevel.LOW,
                device_id=self._required_text(params, "device_id", max_chars=200),
            )
        if tool == "ai_execute_command":
            command = normalize_command(
                self._required_text(params, "command", max_chars=MAX_COMMAND_CHARS)
            )
            device_id = self._optional_text(params, "device_id", max_chars=200)
            session_id = self._optional_text(params, "session_id", max_chars=240)
            if not device_id and not session_id:
                raise AppControlError("invalid_request", "执行网关命令需要 session_id 或 device_id。")
            return AiDeviceAction(
                "ai_gateway_execute_command",
                "执行网关命令",
                classify_command_risk(command),
                device_id=device_id,
                command=command,
                params={
                    "session_id": session_id,
                    "timeout_seconds": self._integer(params, "timeout_seconds", default=30, minimum=1, maximum=300),
                },
            )
        if tool == "ai_execute_batch":
            raw_commands = params.get("commands")
            if not isinstance(raw_commands, list):
                raise AppControlError("invalid_request", "参数 commands 必须是数组。")
            commands = [normalize_command(str(command)) for command in raw_commands]
            device_id = self._optional_text(params, "device_id", max_chars=200)
            session_id = self._optional_text(params, "session_id", max_chars=240)
            if not device_id and not session_id:
                raise AppControlError("invalid_request", "执行网关批量命令需要 session_id 或 device_id。")
            risk = max((classify_command_risk(command) for command in commands), default=RiskLevel.LOW)
            return AiDeviceAction(
                "ai_gateway_execute_batch",
                "批量执行网关命令",
                risk,
                device_id=device_id,
                params={
                    "commands": commands,
                    "session_id": session_id,
                    "command_timeout_seconds": self._integer(params, "command_timeout_seconds", default=30, minimum=1, maximum=300),
                },
            )
        if tool == "ai_execute_script":
            script = self._required_text(params, "script", max_chars=MAX_COMMAND_CHARS * 8)
            device_id = self._optional_text(params, "device_id", max_chars=200)
            session_id = self._optional_text(params, "session_id", max_chars=240)
            if not device_id and not session_id:
                raise AppControlError("invalid_request", "执行网关脚本需要 session_id 或 device_id。")
            risk = max((classify_command_risk(line) for line in script.splitlines() if line.strip()), default=RiskLevel.LOW)
            return AiDeviceAction(
                "ai_gateway_execute_script",
                "执行网关脚本",
                risk,
                device_id=device_id,
                params={
                    "script": script,
                    "shell": self._optional_text(params, "shell", max_chars=100),
                    "session_id": session_id,
                    "timeout_seconds": self._integer(params, "timeout_seconds", default=30, minimum=1, maximum=300),
                },
            )
        if tool == "ai_upload_file":
            return AiDeviceAction(
                "ai_gateway_upload_file",
                "上传文件到设备",
                RiskLevel.FLOW,
                device_id=self._required_text(params, "device_id", max_chars=200),
                params={
                    "source_path": self._required_text(params, "source_path", max_chars=1_024),
                    "destination_path": self._required_text(params, "destination_path", max_chars=1_024),
                    "overwrite": self._boolean(params, "overwrite", default=False),
                },
            )
        if tool == "ai_download_file":
            return AiDeviceAction(
                "ai_gateway_download_file",
                "从设备下载文件",
                RiskLevel.LOW,
                device_id=self._required_text(params, "device_id", max_chars=200),
                params={
                    "source_path": self._required_text(params, "source_path", max_chars=1_024),
                    "destination_path": self._required_text(params, "destination_path", max_chars=1_024),
                },
            )
        if tool == "ai_get_result":
            return AiDeviceAction(
                "ai_gateway_get_result",
                "读取网关执行结果",
                RiskLevel.OBSERVE,
                params={
                    "result_id": self._required_text(params, "result_id", max_chars=80),
                    "include_raw": self._boolean(params, "include_raw", default=False),
                },
            )
        if tool == "ai_run_skill":
            device_id = self._optional_text(params, "device_id", max_chars=200)
            session_id = self._optional_text(params, "session_id", max_chars=240)
            if not device_id and not session_id:
                raise AppControlError("invalid_request", "运行 Skill 需要 session_id 或 device_id。")
            return AiDeviceAction(
                "ai_gateway_run_skill",
                "运行网关 Skill",
                RiskLevel.FLOW,
                device_id=device_id,
                params={
                    "skill_name": self._required_text(params, "skill_name", max_chars=200),
                    "params": dict(params.get("params") or {}),
                    "session_id": session_id,
                    "timeout_seconds": self._integer(params, "timeout_seconds", default=60, minimum=1, maximum=3600),
                },
            )
        device_id = self._required_text(params, "device_id", max_chars=200)
        if tool == "device_get":
            return AiDeviceAction(
                "device_get",
                "读取设备详情",
                RiskLevel.OBSERVE,
                device_id=device_id,
            )
        if tool == "device_select":
            return AiDeviceAction(
                "select_device",
                "选择设备",
                RiskLevel.OBSERVE,
                device_id=device_id,
            )
        if tool == "session_open":
            return AiDeviceAction(
                "open_session",
                "打开终端会话",
                RiskLevel.LOW,
                device_id=device_id,
            )
        if tool == "terminal_send_command":
            command = self._required_text(
                params,
                "command",
                max_chars=MAX_COMMAND_CHARS,
            )
            normalized = normalize_command(command)
            return AiDeviceAction(
                "send_command",
                "发送终端命令",
                classify_command_risk(normalized),
                device_id=device_id,
                command=normalized,
            )
        if tool == "terminal_read":
            max_chars = self._integer(
                params,
                "max_chars",
                default=DEFAULT_OUTPUT_CHARS,
                minimum=1,
                maximum=MAX_OUTPUT_CHARS,
            )
            return AiDeviceAction(
                "read_terminal",
                "读取终端输出",
                RiskLevel.OBSERVE,
                device_id=device_id,
                params={"max_chars": max_chars},
            )
        if tool == "package_upgrade_start":
            return AiDeviceAction(
                "run_package_upgrade",
                "启动自动换包流程",
                RiskLevel.FLOW,
                device_id=device_id,
            )
        if tool == "file_transfer_start":
            return AiDeviceAction(
                "start_managed_file_transfer",
                "启动托管文件传输",
                RiskLevel.FLOW,
                device_id=device_id,
                params={
                    "source_path": self._required_text(
                        params,
                        "source_path",
                        max_chars=1_024,
                    ),
                    "destination_path": self._required_text(
                        params,
                        "destination_path",
                        max_chars=1_024,
                    ),
                    "overwrite": self._boolean(
                        params,
                        "overwrite",
                        default=False,
                    ),
                },
            )
        raise AppControlError("unknown_tool", f"未知工具: {tool}", status=404)
    def _terminal_target(self, params: dict[str, Any]) -> tuple[str, str]:
        device_id = self._optional_text(params, "device_id", max_chars=200)
        session_id = self._optional_text(params, "session_id", max_chars=240)
        if not device_id and not session_id:
            raise AppControlError(
                "invalid_request",
                "执行终端计划需要 session_id 或 device_id。",
            )
        return device_id, session_id
    @staticmethod
    def _terminal_plan_runs_async(
        mode: str,
        total_timeout_seconds: float,
        *,
        has_state_wait: bool,
    ) -> bool:
        if mode == "sync" and total_timeout_seconds > 60:
            raise AppControlError(
                "invalid_request",
                "同步终端计划的总超时不能超过 60 秒，请使用 async 模式。",
            )
        if mode == "async":
            return True
        if mode == "sync":
            return False
        return total_timeout_seconds > 60 or has_state_wait
    @staticmethod
    def _approval_reason(action: AiDeviceAction) -> str:
        if action.risk == RiskLevel.FLOW:
            return "该操作会启动受控设备变更流程。"
        if action.risk == RiskLevel.HIGH:
            return "命令可能重启设备、删除数据或修改启动配置。"
        return "命令可能修改设备配置或传输文件。"

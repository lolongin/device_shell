"""Gateway execution orchestration driven on the HTTP server thread."""

from __future__ import annotations

from typing import Any, Callable

from ..ai_device_ops import AiDeviceAction, AiDeviceToolResult, RiskLevel
from ..ai_gateway.service import GatewayUnavailableError
from ..ai_gateway.skills import SkillLoadError
from .core import AppControlError


class AiGatewayExecutionMixin:
    def _execute_ai_gateway_create_session(self, action: AiDeviceAction) -> AiDeviceToolResult:
        """Open a device session and wait for connected (HTTP thread)."""
        session_action = AiDeviceAction(
            "session_manage",
            "创建网关会话",
            RiskLevel.LOW,
            device_id=action.device_id,
            params={
                "action": "open",
                "protocol": "auto",
                "session_id": "",
                "timeout_seconds": 15,
            },
        )
        result = self._execute_session_manage(session_action)
        if not result.ok:
            return result
        session = (
            dict(result.data.get("session") or {})
            if isinstance(result.data, dict)
            else {}
        )
        session_id = str(session.get("session_id") or "")
        connected = str(session.get("status") or "") == "connected"
        return AiDeviceToolResult(
            action,
            ok=True,
            message=f"网关会话就绪: {session_id}",
            data={
                "session_id": session_id,
                "connected": connected,
                "session": session,
            },
        )

    def _execute_ai_gateway_execute(self, action: AiDeviceAction) -> AiDeviceToolResult:
        """Drive ai_execute_command/batch/script/run_skill on the HTTP thread."""
        gateway = getattr(self.backend, "gateway_service", lambda: None)()
        if gateway is None:
            raise AppControlError("gateway_unavailable", "网关服务未初始化。", status=409)
        executor = self._gateway_executor(action)
        session_id = str(action.params.get("session_id") or "")
        try:
            if action.kind == "ai_gateway_execute_command":
                data = gateway.execute_command(
                    action.command,
                    session_id,
                    timeout_seconds=int(action.params.get("timeout_seconds", 30)),
                    executor=executor,
                )
            elif action.kind == "ai_gateway_execute_batch":
                data = gateway.execute_batch(
                    list(action.params.get("commands") or []),
                    session_id,
                    command_timeout_seconds=int(action.params.get("command_timeout_seconds", 30)),
                    executor=executor,
                )
            elif action.kind == "ai_gateway_execute_script":
                style = getattr(self.backend, "gateway_script_style", lambda _d: "network")(action.device_id)
                data = gateway.execute_script(
                    str(action.params.get("script") or ""),
                    session_id,
                    shell=str(action.params.get("shell") or ""),
                    timeout_seconds=int(action.params.get("timeout_seconds", 30)),
                    is_network_device=(style != "linux"),
                    executor=executor,
                )
            elif action.kind == "ai_gateway_run_skill":
                data = gateway.run_skill(
                    str(action.params.get("skill_name") or ""),
                    dict(action.params.get("params") or {}),
                    session_id=session_id,
                    timeout_seconds=int(action.params.get("timeout_seconds", 60)),
                    executor=executor,
                )
            else:
                raise AppControlError("unknown_tool", f"未知网关动作: {action.kind}", status=404)
        except GatewayUnavailableError as exc:
            raise AppControlError(exc.code, str(exc), status=409) from exc
        except SkillLoadError as exc:
            raise AppControlError(exc.code, str(exc), status=400) from exc
        return AiDeviceToolResult(action, ok=True, message="网关执行完成。", data=data)

    def _gateway_executor(
        self,
        action: AiDeviceAction,
    ) -> Callable[[str, str, int], dict[str, Any]]:
        """Build the synchronous command executor: start-on-Qt + wait-on-HTTP."""
        def run(command: str, session_id: str, timeout_seconds: int) -> dict[str, Any]:
            plan_action = AiDeviceAction(
                "terminal_plan_start",
                f"网关执行: {command[:80]}",
                RiskLevel.LOW,  # actual risk already gated on the outer action
                device_id=action.device_id,
                params={
                    "plan_kind": "batch",
                    "commands": [command],
                    "session_id": session_id,
                    "command_timeout_seconds": int(timeout_seconds),
                    "total_timeout_seconds": int(timeout_seconds) + 5,
                    "max_output_chars_per_step": 16_384,
                    "mode": "auto",
                    "run_async": False,
                },
            )
            result = self._execute_terminal_plan(plan_action)
            if not result.ok:
                raise AppControlError(
                    result.error_code or "execution_failed",
                    result.message,
                    status=result.http_status or 409,
                )
            data = dict(result.data or {})
            status_map = {
                "completed": "success",
                "timed_out": "timeout",
                "failed": "failed",
                "cancelled": "failed",
                "disconnected": "failed",
            }
            status = status_map.get(str(data.get("status") or ""), "failed")
            output = "\n".join(
                str(step.get("output") or "")
                for step in data.get("steps", [])
                if isinstance(step, dict) and step.get("output")
            )
            return {
                "status": status,
                "output": output,
                "exit_code": 1 if data.get("error_code") else 0,
            }
        return run

"""Map Agent tool calls to existing application services."""

from __future__ import annotations

from typing import Any

from device_tui.application.ai.service import AiApplicationService
from device_tui.application.errors import ApplicationError
from device_tui.application.ai.llm.models import ToolCall

from .context import AgentContext


class AgentToolExecutor:
    def __init__(self, ai_service: AiApplicationService) -> None:
        self._ai = ai_service

    async def execute(
        self,
        tool_call: ToolCall,
        context: AgentContext,
    ) -> dict[str, Any]:
        if tool_call.name not in {"terminal_execute", "terminal_execute_batch"}:
            return {
                "ok": False,
                "error": f"Unknown tool: {tool_call.name}",
            }
        if tool_call.name == "terminal_execute":
            command = str(tool_call.arguments.get("command") or "").strip()
            if not command:
                return {"ok": False, "error": "terminal_execute requires command"}
            commands = [command]
        else:
            raw_commands = tool_call.arguments.get("commands")
            if not isinstance(raw_commands, list):
                return {"ok": False, "error": "terminal_execute_batch requires commands"}
            commands = [str(item).strip() for item in raw_commands if str(item).strip()]
            if not commands:
                return {"ok": False, "error": "terminal_execute_batch requires commands"}
        try:
            session = await self._ai.resolve_session(
                session_id=context.session_id,
                device_id=context.device_id,
                protocol=str(
                    tool_call.arguments.get("protocol")
                    or context.variables.get("protocol")
                    or "auto"
                ),
                source="agent",
            )
            context.device_id = session.device_id
            context.session_id = session.id
            result = await self._ai.run_terminal_batch(
                commands,
                session_id=session.id,
                command_timeout_seconds=max(
                    1,
                    min(600, int(tool_call.arguments.get("timeout_seconds") or 30)),
                ),
                max_output_chars=max(
                    256,
                    min(100_000, int(tool_call.arguments.get("max_output_chars") or 16_384)),
                ),
                source="agent",
                kind="agent_terminal_execute",
            )
            return {
                "ok": result.get("status") == "completed",
                "status": result.get("status"),
                "device_id": session.device_id,
                "session_id": session.id,
                "output": self._output(result),
                "command_count": len(commands),
                "execution": result,
            }
        except ApplicationError as exc:
            return {
                "ok": False,
                "error": exc.message,
                "error_code": exc.code,
                "details": exc.details,
            }
        except (TypeError, ValueError) as exc:
            return {"ok": False, "error": str(exc), "error_code": "invalid_tool_arguments"}

    @staticmethod
    def _output(result: dict[str, Any]) -> str:
        return "".join(
            str(step.get("output") or "")
            for step in result.get("steps", [])
            if isinstance(step, dict)
        )[-100_000:]

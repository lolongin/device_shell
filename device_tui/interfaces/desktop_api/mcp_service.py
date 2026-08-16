"""Compatibility facade mapping the existing MCP tools to desktop application services."""

from __future__ import annotations

import asyncio
from dataclasses import asdict
import threading
from typing import Any

from device_tui.application import AiApplicationService, ApplicationError, DesktopApplication
from device_tui.application.errors import ResourceNotFoundError, UnsupportedOperationError
from .terminal_executor import BackendTerminalExecutor


class DesktopMcpService:
    """Serve the legacy MCP tool names without a Qt window or UI dispatcher."""

    def __init__(
        self,
        desktop: DesktopApplication,
        terminal_executor: BackendTerminalExecutor,
        ai: AiApplicationService,
    ) -> None:
        self.desktop = desktop
        self.terminal_executor = terminal_executor
        self.ai = ai
        self._selected_device_id = ""
        self._idempotency: dict[str, tuple[int, dict[str, Any]]] = {}
        self._lock = threading.RLock()

    async def invoke(self, tool: str, params: dict[str, Any]) -> tuple[int, dict[str, Any]]:
        idempotency_key = str(params.get("idempotency_key") or "").strip()
        cache_key = f"{tool}\0{idempotency_key}" if idempotency_key else ""
        if cache_key:
            with self._lock:
                cached = self._idempotency.get(cache_key)
            if cached is not None:
                return cached[0], dict(cached[1])
        handler = getattr(self, f"_tool_{tool}", None)
        if not callable(handler):
            return self._error(404, "tool_not_found", f"Unsupported MCP tool: {tool}")
        try:
            data = await handler(dict(params))
        except ApplicationError as exc:
            return self._error(409 if exc.code == "conflict" else 400, exc.code, exc.message, exc.details)
        except KeyError as exc:
            return self._error(404, "resource_not_found", f"Unknown resource: {exc}")
        except Exception as exc:  # keep the compatibility envelope stable
            return self._error(400, "mcp_execution_failed", str(exc))
        self.ai.record_mcp_audit(tool, params, status=200)
        response = self._success(data)
        if cache_key:
            with self._lock:
                self._idempotency[cache_key] = (200, dict(response))
        return 200, response

    async def _tool_system_status(self, _params: dict[str, Any]) -> dict[str, Any]:
        return {
            "status": "ready",
            "approval_mode": "disabled",
            "selected_device_id": self._selected_device_id,
            "sessions": [self._session_payload(item) for item in self.desktop.sessions.list_sessions()],
            "operations": [asdict(item) for item in self.desktop.operations.list(limit=50)],
        }

    async def _tool_device_list(self, _params: dict[str, Any]) -> dict[str, Any]:
        inventory = self.desktop.devices.list_inventory()
        return {
            "current_user": inventory.current_user,
            "devices": [self._device_payload(item) for item in inventory.devices],
        }

    async def _tool_device_get(self, params: dict[str, Any]) -> dict[str, Any]:
        return {"device": self._device_payload(self.desktop.devices.require_device(self._text(params, "device_id")))}

    async def _tool_device_select(self, params: dict[str, Any]) -> dict[str, Any]:
        device = self.desktop.devices.require_device(self._text(params, "device_id"))
        self._selected_device_id = device.id
        return {"selected_device_id": device.id, "device": self._device_payload(device)}

    async def _tool_session_open(self, params: dict[str, Any]) -> dict[str, Any]:
        session, reused = await self._open_or_reuse(self._text(params, "device_id"), "auto")
        return {"session": self._session_payload(session), "reused": reused}

    async def _tool_session_list(self, params: dict[str, Any]) -> dict[str, Any]:
        device_id = str(params.get("device_id") or "")
        sessions = [self._session_payload(item) for item in self.desktop.sessions.list_sessions()]
        if device_id:
            sessions = [item for item in sessions if item["device_id"] == device_id]
        return {"sessions": sessions}

    async def _tool_session_manage(self, params: dict[str, Any]) -> dict[str, Any]:
        action = self._text(params, "action").casefold()
        protocol = str(params.get("protocol") or "auto").casefold()
        device_id = str(params.get("device_id") or "")
        session_id = str(params.get("session_id") or "")
        if action == "open":
            session, reused = await self._open_or_reuse(device_id, protocol)
            return {"session": self._session_payload(session), "reused": reused}
        session = self._resolve_session(session_id=session_id, device_id=device_id)
        if action == "status":
            return {"session": self._session_payload(session)}
        if action == "reconnect":
            return {"session": self._session_payload(await self.desktop.sessions.reconnect(session.id))}
        if action == "disconnect":
            self.desktop.upgrades.cancel_session(session.id)
            self.desktop.transfers.cancel_session(session.id)
            return {"session": self._session_payload(await self.desktop.sessions.disconnect(session.id))}
        if action == "close":
            self.desktop.automation.cancel_session(session.id, reason="mcp_close")
            self.desktop.upgrades.cancel_session(session.id)
            self.desktop.transfers.cancel_session(session.id)
            await self.desktop.sessions.close(session.id)
            return {"session_id": session.id, "closed": True}
        raise UnsupportedOperationError(f"Unsupported session action: {action}")

    async def _tool_terminal_run(self, params: dict[str, Any]) -> dict[str, Any]:
        session = await self._terminal_target(params, ensure=bool(params.get("ensure_session", True)))
        result = await self.ai.run_terminal_batch(
            self._commands(params),
            session_id=session.id,
            command_timeout_seconds=int(params.get("command_timeout_seconds") or 30),
            total_timeout_seconds=params.get("total_timeout_seconds"),
            max_output_chars=int(params.get("max_output_chars_per_step") or 16_384),
            source="mcp",
            kind="terminal_run",
        )
        return self._execution_payload(result)

    async def _tool_terminal_execute(self, params: dict[str, Any]) -> dict[str, Any]:
        session = await self._terminal_target(params, ensure=True)
        result = await self.ai.run_terminal_batch(
            [self._text(params, "command")],
            session_id=session.id,
            command_timeout_seconds=int(params.get("timeout_seconds") or 30),
            total_timeout_seconds=int(params.get("timeout_seconds") or 30) + 5,
            max_output_chars=int(params.get("max_output_chars") or 16_384),
            source="mcp",
            kind="terminal_execute",
        )
        payload = self._execution_payload(result)
        payload["output"] = self.ai._result_output(result)
        payload["completion_reason"] = "prompt" if result.get("status") == "completed" else str(result.get("status") or "failed")
        return payload

    async def _tool_terminal_execute_batch(self, params: dict[str, Any]) -> dict[str, Any]:
        session = await self._terminal_target(params, ensure=True)
        result = await self.ai.run_terminal_batch(
            self._commands(params),
            session_id=session.id,
            command_timeout_seconds=int(params.get("command_timeout_seconds") or 30),
            total_timeout_seconds=params.get("total_timeout_seconds"),
            max_output_chars=int(params.get("max_output_chars_per_step") or 16_384),
            source="mcp",
            kind="terminal_execute_batch",
        )
        return self._execution_payload(result)

    async def _tool_terminal_interact(self, params: dict[str, Any]) -> dict[str, Any]:
        session = await self._terminal_target(params, ensure=True)
        steps = params.get("steps")
        if not isinstance(steps, list):
            raise UnsupportedOperationError("Terminal interaction steps must be a list.")
        result = await self.ai.run_terminal_plan(
            session_id=session.id,
            steps=steps,
            total_timeout_seconds=int(params.get("total_timeout_seconds") or 60),
            source="mcp",
            kind="terminal_interact",
        )
        return self._execution_payload(result)

    async def _tool_terminal_send_command(self, params: dict[str, Any]) -> dict[str, Any]:
        session, _ = await self._open_or_reuse(self._text(params, "device_id"), "auto")
        command = self._text(params, "command")
        await self.desktop.commands.send(session.id, command)
        return {"session_id": session.id, "device_id": session.device_id, "command": command, "sent": True}

    async def _tool_terminal_read(self, params: dict[str, Any]) -> dict[str, Any]:
        session = self._resolve_session(device_id=self._text(params, "device_id"))
        log = self.desktop.sessions.read_log(session.id, int(params.get("max_chars") or 4096))
        return {"session_id": session.id, "device_id": session.device_id, "output": log.content, "truncated": log.truncated}

    async def _tool_execution_get(self, params: dict[str, Any]) -> dict[str, Any]:
        return self._execution_payload(self.terminal_executor.get_execution(self._text(params, "execution_id")))

    async def _tool_execution_cancel(self, params: dict[str, Any]) -> dict[str, Any]:
        return self._execution_payload(self.terminal_executor.cancel_execution(self._text(params, "execution_id")))

    async def _tool_file_transfer_list(self, params: dict[str, Any]) -> dict[str, Any]:
        catalog = self.desktop.transfers.list_files(
            relative_path=str(params.get("path") or ""),
            recursive=bool(params.get("recursive", True)),
            limit=int(params.get("limit") or 200),
        )
        return {"files": [item.public_dict() for item in catalog.files], "truncated": catalog.truncated}

    async def _tool_file_transfer_start(self, params: dict[str, Any]) -> dict[str, Any]:
        session, _ = await self._open_or_reuse(self._text(params, "device_id"), "auto")
        operation = self.desktop.transfers.start_upload(
            session_id=session.id,
            source_path=self._text(params, "source_path"),
            destination_path=self._text(params, "destination_path"),
            overwrite=bool(params.get("overwrite", False)),
        )
        return {"operation_id": operation.id, "operation": asdict(operation)}

    async def _tool_package_upgrade_start(self, params: dict[str, Any]) -> dict[str, Any]:
        session, _ = await self._open_or_reuse(self._text(params, "device_id"), "auto")
        packages = [item for item in self.desktop.transfers.list_files(limit=1_000).files if item.name.casefold().endswith(".cc")]
        if not packages:
            raise UnsupportedOperationError("No .cc package is available in the managed transfer root.")
        operation = self.desktop.upgrades.start(session_id=session.id, package_path=packages[0].relative_path)
        return {"operation_id": operation.id, "operation": asdict(operation)}

    async def _tool_operation_get(self, params: dict[str, Any]) -> dict[str, Any]:
        return {"operation": asdict(self.desktop.operations.get(self._text(params, "operation_id")))}

    async def _tool_operation_wait(self, params: dict[str, Any]) -> dict[str, Any]:
        operation_id = self._text(params, "operation_id")
        revision = int(params.get("since_revision") or 0)
        deadline = asyncio.get_running_loop().time() + min(60, max(0, int(params.get("timeout_seconds") or 60)))
        while True:
            record = self.desktop.operations.get(operation_id)
            if record.status in {"completed", "failed", "cancelled"} or record.revision > revision or asyncio.get_running_loop().time() >= deadline:
                return {"operation": asdict(record)}
            await asyncio.sleep(0.1)

    async def _tool_operation_cancel(self, params: dict[str, Any]) -> dict[str, Any]:
        return {"operation": asdict(self.desktop.operations.cancel(self._text(params, "operation_id")))}

    async def _tool_ai_create_session(self, params: dict[str, Any]) -> dict[str, Any]:
        return await self._tool_session_open(params)

    async def _tool_ai_execute_command(self, params: dict[str, Any]) -> dict[str, Any]:
        session = await self._terminal_target(params, ensure=True)
        return await self.ai.execute_command(self._text(params, "command"), session_id=session.id, source="mcp", idempotency_key=self._optional_text(params, "idempotency_key"))

    async def _tool_ai_execute_batch(self, params: dict[str, Any]) -> dict[str, Any]:
        session = await self._terminal_target(params, ensure=True)
        return await self.ai.execute_batch(self._commands(params), session_id=session.id, command_timeout_seconds=int(params.get("command_timeout_seconds") or 30), source="mcp", idempotency_key=self._optional_text(params, "idempotency_key"))

    async def _tool_ai_execute_script(self, params: dict[str, Any]) -> dict[str, Any]:
        session = await self._terminal_target(params, ensure=True)
        return await self.ai.execute_script(self._text(params, "script"), session_id=session.id, timeout_seconds=int(params.get("timeout_seconds") or 30), source="mcp", idempotency_key=self._optional_text(params, "idempotency_key"))

    async def _tool_ai_upload_file(self, params: dict[str, Any]) -> dict[str, Any]:
        return await self._tool_file_transfer_start(params)

    async def _tool_ai_download_file(self, params: dict[str, Any]) -> dict[str, Any]:
        session, _ = await self._open_or_reuse(self._text(params, "device_id"), "auto")
        operation = self.desktop.transfers.start_download(session_id=session.id, source_path=self._text(params, "source_path"), destination_path=self._text(params, "destination_path"), overwrite=False)
        return {"operation_id": operation.id, "operation": asdict(operation)}

    async def _tool_ai_get_result(self, params: dict[str, Any]) -> dict[str, Any]:
        return self.ai.get_result(self._text(params, "result_id"), include_raw=bool(params.get("include_raw", False)))

    async def _tool_ai_run_skill(self, params: dict[str, Any]) -> dict[str, Any]:
        session = await self._terminal_target(params, ensure=True)
        raw_params = params.get("params")
        if not isinstance(raw_params, dict):
            raise UnsupportedOperationError("Skill params must be an object.")
        return await self.ai.run_skill(self._text(params, "skill_name"), raw_params, session_id=session.id, source="mcp", idempotency_key=self._optional_text(params, "idempotency_key"))

    async def _tool_ai_list_skills(self, _params: dict[str, Any]) -> dict[str, Any]:
        return {"skills": self.ai.list_skills()}

    async def _tool_approval_get(self, _params: dict[str, Any]) -> dict[str, Any]:
        raise UnsupportedOperationError("AI approval is disabled by policy.")

    async def _terminal_target(self, params: dict[str, Any], *, ensure: bool) -> Any:
        session_id = self._optional_text(params, "session_id")
        device_id = self._optional_text(params, "device_id")
        if session_id:
            return self._resolve_session(session_id=session_id)
        if not device_id:
            raise UnsupportedOperationError("A session_id or device_id is required.")
        if ensure:
            return (await self._open_or_reuse(device_id, str(params.get("protocol") or "auto")))[0]
        return self._resolve_session(device_id=device_id)

    async def _open_or_reuse(self, device_id: str, protocol: str) -> tuple[Any, bool]:
        for session in self.desktop.sessions.list_sessions():
            if session.device_id == device_id and session.status == "connected":
                return session, True
        device = self.desktop.devices.require_device(device_id)
        kind = protocol if protocol in {"ssh", "telnet", "serial", "simulated"} else self._protocol_for(device)
        return await self.desktop.sessions.create(device_id, kind), False

    def _resolve_session(self, *, session_id: str = "", device_id: str = "") -> Any:
        for session in self.desktop.sessions.list_sessions():
            if session_id and session.id == session_id:
                return session
            if device_id and session.device_id == device_id:
                return session
        raise ResourceNotFoundError("Unknown session", details={"session_id": session_id, "device_id": device_id})

    @staticmethod
    def _protocol_for(device: Any) -> str:
        if str(device.device_type).casefold().startswith("mock"):
            return "simulated"
        if device.ssh_endpoint:
            return "ssh"
        if device.telnet_endpoint:
            return "telnet"
        if device.serial_endpoint:
            return "serial"
        return "simulated"

    @staticmethod
    def _device_payload(device: Any) -> dict[str, Any]:
        payload = asdict(device)
        payload["protocols"] = [kind for kind, endpoint in (("ssh", device.ssh_endpoint), ("telnet", device.telnet_endpoint), ("serial", device.serial_endpoint)) if endpoint]
        if str(device.device_type).casefold().startswith("mock"):
            payload["protocols"] = ["simulated"]
        return payload

    @staticmethod
    def _session_payload(session: Any) -> dict[str, Any]:
        payload = asdict(session)
        payload["session_id"] = session.id
        return payload

    @staticmethod
    def _execution_payload(result: dict[str, Any]) -> dict[str, Any]:
        payload = dict(result)
        payload["timing"] = {"total_ms": payload.get("duration_ms", 0)}
        return payload

    @staticmethod
    def _text(params: dict[str, Any], name: str) -> str:
        value = str(params.get(name) or "").strip()
        if not value:
            raise UnsupportedOperationError(f"{name} is required.")
        return value

    @staticmethod
    def _optional_text(params: dict[str, Any], name: str) -> str:
        return str(params.get(name) or "").strip()

    @staticmethod
    def _commands(params: dict[str, Any]) -> list[str]:
        commands = params.get("commands")
        if not isinstance(commands, list) or not commands:
            raise UnsupportedOperationError("commands must contain at least one entry.")
        return [str(item) for item in commands]

    @staticmethod
    def _success(data: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, "message": "ok", "data": data, "approval": None, "error": None}

    @staticmethod
    def _error(status: int, code: str, message: str, details: dict[str, Any] | None = None) -> tuple[int, dict[str, Any]]:
        return status, {"ok": False, "message": message, "data": {}, "approval": None, "error": {"code": code, "message": message, "details": details or {}}}

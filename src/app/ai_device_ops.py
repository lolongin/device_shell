"""App bridge for AI-assisted device operations."""

from __future__ import annotations

from dataclasses import asdict
import os
from pathlib import Path
from typing import Any

try:
    from PySide6.QtCore import QTimer, Qt
    from PySide6.QtWidgets import (
        QFrame,
        QGroupBox,
        QHBoxLayout,
        QLabel,
        QListWidget,
        QListWidgetItem,
        QPlainTextEdit,
        QPushButton,
        QSizePolicy,
        QVBoxLayout,
        QWidget,
    )
except ModuleNotFoundError:
    QTimer = None
    Qt = None
    QFrame = None
    QGroupBox = None
    QHBoxLayout = None
    QLabel = None
    QListWidget = None
    QListWidgetItem = None
    QPlainTextEdit = None
    QPushButton = None
    QSizePolicy = None
    QVBoxLayout = None
    QWidget = None

from ..ai_device_ops import (
    AiDeviceAction,
    AiDevicePlan,
    AiDeviceToolResult,
    DeviceSnapshot,
    RiskLevel,
    SimpleAiDevicePlanner,
    classify_command_risk,
)
from ..app_control import (
    APPROVAL_MODE_REQUIRED,
    AppControlError,
    AppControlService,
    ApprovalRecord,
    AuditLogger,
)
from ..app_control_server import (
    AppControlHttpServer,
    default_audit_path,
)
from ..managed_file_transfer import ManagedTransferError
from ..terminal_execution import incremental_terminal_output
from ..terminal_orchestration import (
    TerminalPlanError,
    TerminalExecutionCoordinator,
    TerminalInput,
    build_batch_plan,
    parse_terminal_plan,
)


class AiDeviceOpsMixin:
    """Expose a guarded device-operation surface for AI planners."""

    def initialize_terminal_execution_coordinator(self) -> None:
        def schedule(delay_ms: int, callback: Any) -> None:
            if QTimer is None:
                callback()
                return
            QTimer.singleShot(max(0, delay_ms), callback)

        self.terminal_execution_coordinator = TerminalExecutionCoordinator(
            send_input=self._send_terminal_execution_input,
            resolve_secret=self._resolve_terminal_execution_secret,
            schedule=schedule,
        )

    def _send_terminal_execution_input(
        self,
        session_id: str,
        payload: TerminalInput,
        execution_id: str,
    ) -> None:
        if payload.sensitive:
            self.arm_sensitive_session_echo(session_id, payload.text.rstrip("\r\n"))
        self.send_session_text(
            session_id,
            payload.text,
            origin="ai_execution",
            execution_id=execution_id,
            sensitive=payload.sensitive,
            secret_ref=payload.secret_ref,
        )

    def _resolve_terminal_execution_secret(self, secret_ref: str) -> str:
        if secret_ref == "file_transfer.username":
            service = getattr(self, "transfer_service", None)
            config = getattr(service, "config", None)
            if service is not None and service.is_running and config is not None:
                return config.username
            if hasattr(self, "transfer_username_input"):
                return self.transfer_username_input.text().strip()
            return str(getattr(self, "transfer_username", "")).strip()
        if secret_ref == "file_transfer.password":
            service = getattr(self, "transfer_service", None)
            config = getattr(service, "config", None)
            if service is not None and service.is_running and config is not None:
                return config.password
            if hasattr(self, "transfer_password_input"):
                return self.transfer_password_input.text()
            return str(getattr(self, "transfer_password", ""))
        if secret_ref == "transfer.username":
            if hasattr(self, "package_upgrade_username_input"):
                return self.package_upgrade_username_input.text().strip()
            if hasattr(self, "transfer_username_input"):
                return self.transfer_username_input.text().strip()
            return str(getattr(self, "transfer_username", "")).strip()
        if secret_ref == "transfer.password":
            if hasattr(self, "package_upgrade_password_input"):
                return self.package_upgrade_password_input.text()
            if hasattr(self, "transfer_password_input"):
                return self.transfer_password_input.text()
            return str(getattr(self, "transfer_password", ""))
        raise KeyError(secret_ref)

    def _build_ai_device_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("leftRail")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(8)

        group = QGroupBox("AI 设备助手")
        group.setObjectName("navShell")
        group_layout = QVBoxLayout(group)
        group_layout.setSpacing(8)

        title = QLabel("AI 设备助手")
        title.setObjectName("railTitle")
        group_layout.addWidget(title)
        copy = QLabel("先生成计划，再确认执行。高风险命令会进入确认门，换包走受控状态机。")
        copy.setObjectName("railCopy")
        copy.setWordWrap(True)
        if QSizePolicy is not None:
            copy.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        group_layout.addWidget(copy)

        self.ai_device_prompt_input = QPlainTextEdit()
        self.ai_device_prompt_input.setObjectName("transferLogOutput")
        self.ai_device_prompt_input.setPlaceholderText("例如：给模拟终端执行自动换包")
        self.ai_device_prompt_input.setMaximumHeight(92)
        self.ai_device_prompt_input.setPlainText("给模拟终端执行自动换包")
        group_layout.addWidget(self.ai_device_prompt_input)

        action_row = QHBoxLayout()
        action_row.setSpacing(6)
        self.ai_device_plan_button = QPushButton("生成计划")
        self.ai_device_plan_button.setObjectName("compactGhostButton")
        self.ai_device_execute_button = QPushButton("确认执行")
        self.ai_device_execute_button.setObjectName("primaryButton")
        self.ai_device_execute_button.setEnabled(False)
        action_row.addWidget(self.ai_device_plan_button, 1)
        action_row.addWidget(self.ai_device_execute_button, 1)
        group_layout.addLayout(action_row)

        self.ai_device_status_label = QLabel("输入目标后生成受控执行计划。")
        self.ai_device_status_label.setObjectName("activeFilterText")
        self.ai_device_status_label.setWordWrap(True)
        group_layout.addWidget(self.ai_device_status_label)

        self.ai_external_approval_title = QLabel("外部 Tool Calling 审批")
        self.ai_external_approval_title.setObjectName("sectionCaption")
        group_layout.addWidget(self.ai_external_approval_title)
        self.ai_external_control_status_label = QLabel("控制服务尚未启动。")
        self.ai_external_control_status_label.setObjectName("activeFilterText")
        self.ai_external_control_status_label.setWordWrap(True)
        group_layout.addWidget(self.ai_external_control_status_label)

        self.ai_external_approval_list = QListWidget()
        self.ai_external_approval_list.setObjectName("transferLogOutput")
        self.ai_external_approval_list.setMaximumHeight(116)
        self.ai_external_approval_list.setToolTip("外部 AI 请求的中高风险设备操作")
        group_layout.addWidget(self.ai_external_approval_list)

        approval_row = QHBoxLayout()
        approval_row.setSpacing(6)
        self.ai_external_approve_button = QPushButton("批准")
        self.ai_external_approve_button.setObjectName("primaryButton")
        self.ai_external_approve_button.setEnabled(False)
        self.ai_external_reject_button = QPushButton("拒绝")
        self.ai_external_reject_button.setObjectName("compactGhostButton")
        self.ai_external_reject_button.setProperty("buttonRole", "danger")
        self.ai_external_reject_button.setEnabled(False)
        approval_row.addWidget(self.ai_external_approve_button, 1)
        approval_row.addWidget(self.ai_external_reject_button, 1)
        group_layout.addLayout(approval_row)

        output_frame = QFrame()
        output_frame.setObjectName("transferConfigCard")
        output_layout = QVBoxLayout(output_frame)
        output_layout.setContentsMargins(10, 8, 10, 8)
        output_layout.setSpacing(6)
        output_title = QLabel("计划与执行记录")
        output_title.setObjectName("sectionCaption")
        output_layout.addWidget(output_title)
        self.ai_device_plan_output = QPlainTextEdit()
        self.ai_device_plan_output.setObjectName("transferLogOutput")
        self.ai_device_plan_output.setReadOnly(True)
        self.ai_device_plan_output.setMinimumHeight(220)
        output_layout.addWidget(self.ai_device_plan_output)
        group_layout.addWidget(output_frame)

        layout.addWidget(group)
        layout.addStretch(1)
        self.current_ai_device_plan: AiDevicePlan | None = None
        return panel

    def wire_ai_device_events(self) -> None:
        self.ai_device_plan_button.clicked.connect(self.generate_ai_device_plan)
        self.ai_device_execute_button.clicked.connect(self.execute_current_ai_device_plan)
        self.ai_external_approval_list.currentItemChanged.connect(
            self.update_external_approval_controls
        )
        self.ai_external_approve_button.clicked.connect(
            self.approve_selected_external_action
        )
        self.ai_external_reject_button.clicked.connect(
            self.reject_selected_external_action
        )

    def start_app_control_server(self, *, state_path: Path | None = None) -> bool:
        server = getattr(self, "app_control_server", None)
        if server is not None and server.is_running:
            self.apply_external_approval_mode(server.base_url)
            return True
        audit = AuditLogger(default_audit_path())
        service = AppControlService(
            self,
            dispatcher=lambda callback, timeout: self.call_on_ui_thread(
                callback,
                timeout=timeout,
            ),
            audit=audit,
            on_approval_created=lambda record: self.dispatch_ui(
                self.notify_external_approval,
                record,
            ),
        )
        server = AppControlHttpServer(service, state_path=state_path)
        self.app_control_service = service
        self.app_control_server = server
        try:
            base_url = server.start()
        except OSError as exc:
            self.app_control_service = None
            self.app_control_server = None
            self.ai_external_control_status_label.setText(
                f"控制服务启动失败: {exc}"
            )
            self.set_status_message(f"AI 控制服务启动失败: {exc}")
            return False
        self.apply_external_approval_mode(base_url)
        self.set_status_message(f"AI 控制服务已启动: {base_url}")
        return True

    def apply_external_approval_mode(self, base_url: str) -> None:
        service = getattr(self, "app_control_service", None)
        approval_required = bool(
            service is not None
            and service.approval_mode == APPROVAL_MODE_REQUIRED
        )
        self.ai_external_approval_title.setVisible(approval_required)
        self.ai_external_approval_list.setVisible(approval_required)
        self.ai_external_approve_button.setVisible(approval_required)
        self.ai_external_reject_button.setVisible(approval_required)
        if approval_required:
            self.ai_external_control_status_label.setText(
                f"本机控制服务已启动: {base_url}；Device TUI 内部审批已启用。"
            )
            return
        self.ai_external_approval_list.clear()
        self.ai_external_control_status_label.setText(
            f"本机控制服务已启动: {base_url}；Device TUI 内部审批已关闭，"
            "外部工具动作将直接执行。"
        )

    def stop_app_control_server(self) -> None:
        server = getattr(self, "app_control_server", None)
        self.app_control_server = None
        self.app_control_service = None
        if server is not None:
            server.stop()

    def notify_external_approval(self, record: ApprovalRecord) -> None:
        if not hasattr(self, "ai_external_approval_list"):
            return
        service = getattr(self, "app_control_service", None)
        if service is None or not service.requires_device_approval:
            return
        for index in range(self.ai_external_approval_list.count()):
            item = self.ai_external_approval_list.item(index)
            if item.data(Qt.UserRole) == record.id:
                return
        command = record.action.command or record.action.label
        text = (
            f"[{self.ai_risk_label(record.action.risk)}] "
            f"{record.action.device_id} | {command}"
        )
        item = QListWidgetItem(text)
        item.setData(Qt.UserRole, record.id)
        item.setToolTip(record.reason)
        self.ai_external_approval_list.addItem(item)
        self.ai_external_approval_list.setCurrentItem(item)
        self.ai_external_control_status_label.setText(
            f"等待确认: {record.source} 请求 {record.action.label}"
        )
        self.set_status_message("外部 AI 有一项设备操作等待确认。")

    def update_external_approval_controls(self, *_args: Any) -> None:
        selected = self.ai_external_approval_list.currentItem() is not None
        self.ai_external_approve_button.setEnabled(selected)
        self.ai_external_reject_button.setEnabled(selected)

    def selected_external_approval_id(self) -> str:
        item = self.ai_external_approval_list.currentItem()
        if item is None:
            return ""
        return str(item.data(Qt.UserRole) or "")

    def approve_selected_external_action(self) -> None:
        approval_id = self.selected_external_approval_id()
        service = getattr(self, "app_control_service", None)
        if not approval_id or service is None:
            return
        try:
            record = service.approve(approval_id)
        except AppControlError as exc:
            self.ai_external_control_status_label.setText(str(exc))
            return
        self.remove_external_approval_item(approval_id)
        self.ai_external_control_status_label.setText(
            f"已批准一次性执行: {record.action.label}"
        )

    def reject_selected_external_action(self) -> None:
        approval_id = self.selected_external_approval_id()
        service = getattr(self, "app_control_service", None)
        if not approval_id or service is None:
            return
        try:
            record = service.reject(approval_id)
        except AppControlError as exc:
            self.ai_external_control_status_label.setText(str(exc))
            return
        self.remove_external_approval_item(approval_id)
        self.ai_external_control_status_label.setText(
            f"已拒绝: {record.action.label}"
        )

    def remove_external_approval_item(self, approval_id: str) -> None:
        for index in range(self.ai_external_approval_list.count()):
            item = self.ai_external_approval_list.item(index)
            if item.data(Qt.UserRole) == approval_id:
                self.ai_external_approval_list.takeItem(index)
                break
        self.update_external_approval_controls()

    def generate_ai_device_plan(self) -> None:
        objective = self.ai_device_prompt_input.toPlainText().strip()
        if not objective:
            self.ai_device_status_label.setText("请先输入要让 AI 完成的设备目标。")
            return
        planner = SimpleAiDevicePlanner()
        plan = planner.build_plan(
            objective,
            self.ai_device_snapshots(),
            selected_device_id=self.selected_ai_device_id(),
        )
        self.current_ai_device_plan = plan
        self.ai_device_plan_output.setPlainText(self.format_ai_device_plan(plan))
        self.ai_device_execute_button.setEnabled(bool(plan.actions))
        status = "计划需要确认后执行。" if plan.requires_confirmation else "计划可自动执行。"
        self.ai_device_status_label.setText(status)

    def execute_current_ai_device_plan(self) -> None:
        plan = getattr(self, "current_ai_device_plan", None)
        if plan is None:
            self.generate_ai_device_plan()
            plan = getattr(self, "current_ai_device_plan", None)
        if plan is None or not plan.actions:
            self.ai_device_status_label.setText("没有可执行的 AI 计划。")
            return

        lines = [self.format_ai_device_plan(plan), "", "执行结果:"]
        all_ok = True
        for index, action in enumerate(plan.actions, start=1):
            result = self.execute_ai_device_action(action, approved=action.requires_confirmation)
            all_ok = all_ok and result.ok
            state = "OK" if result.ok else ("NEEDS APPROVAL" if result.approval_required else "FAILED")
            lines.append(f"{index}. [{state}] {action.label}: {result.message}")
            if result.approval_required:
                break
            if not result.ok:
                break
        self.ai_device_plan_output.setPlainText("\n".join(lines))
        self.ai_device_status_label.setText("AI 计划已启动。" if all_ok else "AI 计划已停住，请查看执行记录。")

    def format_ai_device_plan(self, plan: AiDevicePlan) -> str:
        lines = [
            f"目标: {plan.objective}",
            f"摘要: {plan.summary}",
        ]
        if plan.warnings:
            lines.append("提醒:")
            lines.extend(f"- {warning}" for warning in plan.warnings)
        lines.append("动作:")
        for index, action in enumerate(plan.actions, start=1):
            confirm = "需要确认" if action.requires_confirmation else "自动允许"
            command = f" | {action.command}" if action.command else ""
            device = f" | device={action.device_id}" if action.device_id else ""
            lines.append(
                f"{index}. {action.label} [{self.ai_risk_label(action.risk)} / {confirm}]{device}{command}"
            )
        return "\n".join(lines)

    @staticmethod
    def ai_risk_label(risk: RiskLevel) -> str:
        labels = {
            RiskLevel.OBSERVE: "观察",
            RiskLevel.LOW: "低风险",
            RiskLevel.MEDIUM: "中风险",
            RiskLevel.HIGH: "高风险",
            RiskLevel.FLOW: "流程",
        }
        return labels.get(risk, str(int(risk)))

    def ai_device_snapshots(self) -> list[DeviceSnapshot]:
        devices = [
            *getattr(self, "devices", []),
            *getattr(self, "temporary_devices", []),
        ]
        if hasattr(self, "simulated_device"):
            devices.append(self.simulated_device())
        seen: set[str] = set()
        snapshots: list[DeviceSnapshot] = []
        selected_id = getattr(self, "selected_device_id", "")
        for device in devices:
            if device.id in seen:
                continue
            seen.add(device.id)
            kind = "simulated" if getattr(self, "is_simulated_device", lambda _device: False)(device) else "device"
            snapshots.append(
                DeviceSnapshot(
                    id=device.id,
                    name=device.name,
                    status=device.status,
                    domain=device.domain,
                    kind=kind,
                    selected=device.id == selected_id,
                )
            )
        return snapshots

    def selected_ai_device_id(self) -> str:
        return str(getattr(self, "selected_device_id", "") or "")

    def execute_ai_device_action(
        self,
        action: AiDeviceAction,
        *,
        approved: bool = False,
    ) -> AiDeviceToolResult:
        risk = action.risk
        if action.command:
            risk = max(risk, classify_command_risk(action.command))
        guarded_action = AiDeviceAction(
            kind=action.kind,
            label=action.label,
            risk=risk,
            device_id=action.device_id,
            command=action.command,
            params=dict(action.params),
        )
        if guarded_action.requires_confirmation and not approved:
            return AiDeviceToolResult(
                guarded_action,
                ok=False,
                message="该动作需要用户确认后执行。",
                approval_required=True,
            )

        handlers = {
            "system_status": self._execute_ai_system_status,
            "device_get": self._execute_ai_device_get,
            "session_list": self._execute_ai_session_list,
            "session_manage": self._execute_ai_session_manage,
            "terminal_execute_start": self._execute_ai_terminal_start,
            "terminal_execution_snapshot": self._execute_ai_terminal_snapshot,
            "terminal_plan_start": self._execute_ai_terminal_plan_start,
            "terminal_execution_get": self._execute_ai_terminal_execution_get,
            "terminal_execution_cancel": self._execute_ai_terminal_execution_cancel,
            "list_devices": self._execute_ai_list_devices,
            "select_device": self._execute_ai_select_device,
            "open_session": self._execute_ai_open_session,
            "send_command": self._execute_ai_send_command,
            "read_terminal": self._execute_ai_read_terminal,
            "run_package_upgrade": self._execute_ai_package_upgrade,
            "get_package_upgrade_status": self._execute_ai_package_upgrade_status,
            "list_managed_transfer_files": self._execute_ai_managed_transfer_list,
            "start_managed_file_transfer": self._execute_ai_managed_transfer_start,
            "get_managed_file_transfer": self._execute_ai_managed_transfer_get,
            "cancel_managed_file_transfer": self._execute_ai_managed_transfer_cancel,
        }
        handler = handlers.get(guarded_action.kind)
        if handler is None:
            return AiDeviceToolResult(guarded_action, ok=False, message=f"未知 AI 动作: {guarded_action.kind}")
        return handler(guarded_action)

    def _execute_ai_system_status(self, action: AiDeviceAction) -> AiDeviceToolResult:
        sessions = self._ai_session_summaries()
        counts = {
            status: sum(1 for session in sessions if session["status"] == status)
            for status in ("connecting", "connected", "disconnected")
        }
        operation = getattr(self, "package_upgrade_operation_state", {})
        active_operations = int(
            isinstance(operation, dict) and operation.get("status") == "running"
        ) + int(getattr(self, "managed_transfer_active_count", lambda: 0)())
        return AiDeviceToolResult(
            action,
            ok=True,
            message="已读取 Device TUI 运行状态。",
            data={
                "ready": True,
                "pid": os.getpid(),
                "selected_device_id": self.selected_ai_device_id(),
                "session_counts": {
                    "total": len(sessions),
                    **counts,
                },
                "active_operations": active_operations,
            },
        )

    def _execute_ai_device_get(self, action: AiDeviceAction) -> AiDeviceToolResult:
        device = self._ai_device(action.device_id)
        if device is None:
            return self._ai_failure(
                action,
                "device_not_found",
                f"未找到设备: {action.device_id}",
                http_status=404,
            )
        simulated = bool(
            getattr(self, "is_simulated_device", lambda _device: False)(device)
        )
        endpoints: dict[str, dict[str, Any]] = {}
        if simulated:
            endpoints["simulated"] = {"host": "localhost", "port": 0}
        if not simulated and device.telnet_ip.strip():
            endpoints["telnet"] = {
                "host": device.telnet_ip.strip(),
                "port": device.telnet_port,
            }
        if not simulated and device.ssh_ip.strip():
            endpoints["ssh"] = {
                "host": device.ssh_ip.strip(),
                "port": device.ssh_port,
            }
        if not simulated and device.serial_ip.strip():
            endpoints["serial"] = {
                "host": device.serial_ip.strip(),
                "port": device.serial_port,
            }
        return AiDeviceToolResult(
            action,
            ok=True,
            message=f"已读取设备详情: {device.name}",
            data={
                "device": {
                    "id": device.id,
                    "name": device.name,
                    "status": device.status,
                    "domain": device.domain,
                    "device_type": device.device_type,
                    "cpu": device.cpu,
                    "vendor": device.vendor,
                    "model": device.model,
                    "version": device.version,
                    "site": device.site,
                    "rack": device.rack,
                    "board_id": device.board_id,
                    "notes": device.notes,
                    "simulated": simulated,
                    "protocols": list(endpoints),
                    "endpoints": endpoints,
                }
            },
        )

    def _execute_ai_session_list(self, action: AiDeviceAction) -> AiDeviceToolResult:
        device_id = str(action.params.get("device_id") or "")
        sessions = self._ai_session_summaries(device_id=device_id)
        return AiDeviceToolResult(
            action,
            ok=True,
            message=f"读取到 {len(sessions)} 个终端会话。",
            data={"sessions": sessions},
        )

    def _execute_ai_session_manage(self, action: AiDeviceAction) -> AiDeviceToolResult:
        operation = str(action.params.get("action") or "").casefold()
        if operation == "open":
            return self._ai_open_managed_session(action)
        state, failure = self._ai_resolve_session(action)
        if failure is not None:
            return failure
        assert state is not None
        if operation == "status":
            return AiDeviceToolResult(
                action,
                ok=True,
                message=f"会话状态: {self._ai_session_status(state)}",
                data={"session": self._ai_session_summary(state)},
            )
        if operation == "reconnect":
            self.reconnect_session_tab(state.tab_id)
            message = f"已请求重连会话: {state.title}"
        elif operation == "disconnect":
            self.disconnect_session_tab(state.tab_id)
            message = f"已请求断开会话: {state.title}"
        elif operation == "close":
            summary = self._ai_session_summary(state)
            self.close_session_tab(state.tab_id)
            return AiDeviceToolResult(
                action,
                ok=True,
                message=f"已请求关闭会话: {state.title}",
                data={"session": summary, "closed": True},
            )
        else:
            return self._ai_failure(
                action,
                "invalid_request",
                f"未知会话动作: {operation}",
                http_status=400,
            )
        return AiDeviceToolResult(
            action,
            ok=True,
            message=message,
            data={"session": self._ai_session_summary(state)},
        )

    def _execute_ai_terminal_start(self, action: AiDeviceAction) -> AiDeviceToolResult:
        state, failure = self._ai_resolve_session(action, require_connected=True)
        if failure is not None:
            return failure
        assert state is not None
        cursor = int(
            getattr(
                state,
                "output_cursor",
                len(str(getattr(state, "recent_output_buffer", "") or "")),
            )
        )
        command = action.command.strip()
        if not command:
            return self._ai_failure(
                action,
                "invalid_request",
                "命令不能为空。",
                http_status=400,
            )
        self.send_session_text(
            state.tab_id,
            f"{command}\r",
            origin="ai_execution",
        )
        return AiDeviceToolResult(
            action,
            ok=True,
            message=f"已发送命令并开始等待结果: {command}",
            data={
                "session": self._ai_session_summary(state),
                "output_cursor_start": cursor,
            },
        )

    def _execute_ai_terminal_snapshot(self, action: AiDeviceAction) -> AiDeviceToolResult:
        session_id = str(action.params.get("session_id") or "")
        state = getattr(self, "session_tabs_by_id", {}).get(session_id)
        if state is None:
            return self._ai_failure(
                action,
                "session_disconnected",
                f"命令执行期间会话已关闭: {session_id}",
                http_status=409,
            )
        buffer = str(getattr(state, "recent_output_buffer", "") or "")
        output_cursor = int(getattr(state, "output_cursor", len(buffer)))
        buffer_start = int(
            getattr(
                state,
                "output_buffer_start_cursor",
                output_cursor - len(buffer),
            )
        )
        output, truncated = incremental_terminal_output(
            buffer,
            buffer_start_cursor=buffer_start,
            output_cursor=output_cursor,
            requested_cursor=int(action.params.get("cursor", output_cursor)),
            max_chars=int(action.params.get("max_chars", 32768)),
        )
        return AiDeviceToolResult(
            action,
            ok=True,
            message="已读取命令增量输出。",
            data={
                "session_id": state.tab_id,
                "device_id": state.device_id,
                "output": output,
                "output_cursor": output_cursor,
                "truncated": truncated,
                "connected": bool(getattr(state.session, "is_connected", False)),
                "connecting": bool(getattr(state, "connecting", False)),
                "status": self._ai_session_status(state),
            },
        )

    def _execute_ai_terminal_plan_start(self, action: AiDeviceAction) -> AiDeviceToolResult:
        state, failure = self._ai_resolve_session(action, require_connected=True)
        if failure is not None:
            return failure
        assert state is not None
        try:
            plan_kind = str(action.params.get("plan_kind") or "")
            if plan_kind == "batch":
                plan = build_batch_plan(
                    list(action.params.get("commands") or []),
                    command_timeout_seconds=float(
                        action.params.get("command_timeout_seconds", 30)
                    ),
                    total_timeout_seconds=float(
                        action.params.get("total_timeout_seconds", 60)
                    ),
                    max_output_chars=int(
                        action.params.get("max_output_chars_per_step", 16_384)
                    ),
                )
            else:
                plan = parse_terminal_plan(
                    list(action.params.get("steps") or []),
                    total_timeout_seconds=float(
                        action.params.get("total_timeout_seconds", 60)
                    ),
                )
            runner = self.terminal_execution_coordinator.start(
                session_id=state.tab_id,
                device_id=state.device_id,
                plan=plan,
                idempotency_key=str(
                    action.params.get("coordinator_idempotency_key") or ""
                ),
            )
        except TerminalPlanError as exc:
            http_status = 409 if exc.code == "session_busy" else 400
            return self._ai_failure(
                action,
                exc.code,
                str(exc),
                http_status=http_status,
            )
        snapshot = runner.public_dict()
        snapshot["_completion_event"] = runner.completion_event
        return AiDeviceToolResult(
            action,
            ok=True,
            message=f"终端执行已启动: {runner.execution_id}",
            data=snapshot,
        )

    def _execute_ai_terminal_execution_get(
        self,
        action: AiDeviceAction,
    ) -> AiDeviceToolResult:
        execution_id = str(action.params.get("execution_id") or "")
        try:
            runner = self.terminal_execution_coordinator.get(execution_id)
        except TerminalPlanError as exc:
            return self._ai_failure(
                action,
                exc.code,
                str(exc),
                http_status=404,
            )
        return AiDeviceToolResult(
            action,
            ok=True,
            message=f"终端执行状态: {runner.status}",
            data=runner.public_dict(),
        )

    def _execute_ai_terminal_execution_cancel(
        self,
        action: AiDeviceAction,
    ) -> AiDeviceToolResult:
        execution_id = str(action.params.get("execution_id") or "")
        try:
            runner = self.terminal_execution_coordinator.cancel(execution_id)
        except TerminalPlanError as exc:
            return self._ai_failure(
                action,
                exc.code,
                str(exc),
                http_status=404,
            )
        return AiDeviceToolResult(
            action,
            ok=True,
            message=f"终端执行已取消: {execution_id}",
            data=runner.public_dict(),
        )

    def _execute_ai_list_devices(self, action: AiDeviceAction) -> AiDeviceToolResult:
        snapshots = self.ai_device_snapshots()
        return AiDeviceToolResult(
            action,
            ok=True,
            message=f"读取到 {len(snapshots)} 台设备。",
            data={"devices": [asdict(snapshot) for snapshot in snapshots]},
        )

    def _execute_ai_select_device(self, action: AiDeviceAction) -> AiDeviceToolResult:
        device = self.get_device_by_id(action.device_id)
        if device is None and hasattr(self, "simulated_device"):
            simulated = self.simulated_device()
            if simulated.id == action.device_id:
                device = simulated
                self.device_by_id[device.id] = device
        if device is None:
            return AiDeviceToolResult(action, ok=False, message=f"未找到设备: {action.device_id}")
        self.activate_device(device.id)
        return AiDeviceToolResult(action, ok=True, message=f"已选择设备: {device.name}")

    def _execute_ai_open_session(self, action: AiDeviceAction) -> AiDeviceToolResult:
        device = self.get_device_by_id(action.device_id)
        if device is None and hasattr(self, "simulated_device"):
            simulated = self.simulated_device()
            if simulated.id == action.device_id:
                device = simulated
        if device is None:
            return AiDeviceToolResult(action, ok=False, message=f"未找到设备: {action.device_id}")
        self.open_device_session(device)
        return AiDeviceToolResult(action, ok=True, message=f"已请求打开终端: {device.name}")

    def _execute_ai_send_command(self, action: AiDeviceAction) -> AiDeviceToolResult:
        state = self._ai_session_for_device(action.device_id)
        if state is None:
            return AiDeviceToolResult(action, ok=False, message=f"设备没有打开的终端: {action.device_id}")
        command = action.command.strip()
        if not command:
            return AiDeviceToolResult(action, ok=False, message="命令不能为空。")
        self.send_session_text(
            state.tab_id,
            f"{command}\r",
            origin="ai_execution",
        )
        return AiDeviceToolResult(action, ok=True, message=f"已发送命令: {command}", data={"tab_id": state.tab_id})

    def _execute_ai_read_terminal(self, action: AiDeviceAction) -> AiDeviceToolResult:
        state = self._ai_session_for_device(action.device_id)
        if state is None:
            return AiDeviceToolResult(action, ok=False, message=f"设备没有打开的终端: {action.device_id}")
        text = str(getattr(state, "recent_output_buffer", "") or "")
        max_chars = max(1, min(int(action.params.get("max_chars", 4096)), 32768))
        output = text[-max_chars:]
        return AiDeviceToolResult(
            action,
            ok=True,
            message=f"读取终端输出 {len(text)} 字符。",
            data={
                "tab_id": state.tab_id,
                "output": output,
                "total_chars": len(text),
                "truncated": len(text) > len(output),
            },
        )

    def _execute_ai_package_upgrade(self, action: AiDeviceAction) -> AiDeviceToolResult:
        device = self.get_device_by_id(action.device_id)
        if device is None and hasattr(self, "simulated_device"):
            simulated = self.simulated_device()
            if simulated.id == action.device_id:
                device = simulated
                self.device_by_id[device.id] = device
        if device is None:
            return AiDeviceToolResult(action, ok=False, message=f"未找到设备: {action.device_id}")
        self.activate_device(device.id)
        if hasattr(self, "show_left_sidebar_panel"):
            self.show_left_sidebar_panel("package_upgrade")
        started = self.run_package_upgrade_one_click()
        if not started:
            return AiDeviceToolResult(
                action,
                ok=False,
                message="自动换包未启动，请检查系统包和传输配置。",
            )
        return AiDeviceToolResult(action, ok=True, message=f"已启动受控自动换包流程: {device.name}")

    def _execute_ai_package_upgrade_status(
        self,
        action: AiDeviceAction,
    ) -> AiDeviceToolResult:
        snapshot = self.package_upgrade_status_snapshot()
        return AiDeviceToolResult(
            action,
            ok=True,
            message=str(snapshot.get("message") or "已读取自动换包状态。"),
            data=snapshot,
        )

    def _execute_ai_managed_transfer_list(
        self,
        action: AiDeviceAction,
    ) -> AiDeviceToolResult:
        try:
            data = self.managed_transfer_file_list(
                relative_path=str(action.params.get("path") or ""),
                recursive=bool(action.params.get("recursive", True)),
                limit=int(action.params.get("limit", 200)),
            )
        except ManagedTransferError as exc:
            return self._ai_failure(
                action,
                exc.code,
                str(exc),
                http_status=404
                if exc.code in {"transfer_root_unavailable", "transfer_source_not_found"}
                else 400,
            )
        return AiDeviceToolResult(
            action,
            ok=True,
            message=f"共享目录中有 {data['count']} 个可传文件。",
            data=data,
        )

    def _execute_ai_managed_transfer_start(
        self,
        action: AiDeviceAction,
    ) -> AiDeviceToolResult:
        try:
            data = self.start_managed_file_transfer(
                device_id=action.device_id,
                source_path=str(action.params.get("source_path") or ""),
                destination_path=str(action.params.get("destination_path") or ""),
                overwrite=bool(action.params.get("overwrite", False)),
            )
        except ManagedTransferError as exc:
            return self._ai_failure(
                action,
                exc.code,
                str(exc),
                http_status=404
                if exc.code in {"device_not_found", "transfer_source_not_found"}
                else 409,
            )
        ok = data.get("status") != "failed"
        return AiDeviceToolResult(
            action,
            ok=ok,
            message=str(data.get("message") or "托管文件传输已启动。"),
            data=data,
            error_code=str(data.get("error_code") or "") if not ok else "",
            http_status=409,
        )

    def _execute_ai_managed_transfer_get(
        self,
        action: AiDeviceAction,
    ) -> AiDeviceToolResult:
        try:
            data = self.managed_transfer_status_snapshot(
                str(action.params.get("operation_id") or "")
            )
        except ManagedTransferError as exc:
            return self._ai_failure(action, exc.code, str(exc), http_status=404)
        return AiDeviceToolResult(
            action,
            ok=True,
            message=str(data.get("message") or "已读取文件传输状态。"),
            data=data,
        )

    def _execute_ai_managed_transfer_cancel(
        self,
        action: AiDeviceAction,
    ) -> AiDeviceToolResult:
        try:
            data = self.cancel_managed_file_transfer(
                str(action.params.get("operation_id") or "")
            )
        except ManagedTransferError as exc:
            return self._ai_failure(action, exc.code, str(exc), http_status=404)
        return AiDeviceToolResult(
            action,
            ok=True,
            message=str(data.get("message") or "文件传输已取消。"),
            data=data,
        )

    def _ai_device(self, device_id: str) -> Any | None:
        device = self.get_device_by_id(device_id)
        if device is not None:
            return device
        if hasattr(self, "simulated_device"):
            simulated = self.simulated_device()
            if simulated.id == device_id:
                self.device_by_id[simulated.id] = simulated
                return simulated
        return None

    @staticmethod
    def _ai_session_protocol(state: Any) -> str:
        return {
            "device": "telnet",
            "linux": "ssh",
            "serial": "serial",
            "simulated": "simulated",
        }.get(str(getattr(state, "kind", "")), str(getattr(state, "kind", "")))

    @staticmethod
    def _ai_session_status(state: Any) -> str:
        if bool(getattr(state, "connecting", False)):
            return "connecting"
        if bool(getattr(state.session, "is_connected", False)):
            return "connected"
        return "disconnected"

    def _ai_session_summary(self, state: Any) -> dict[str, Any]:
        device = self._ai_device(str(getattr(state, "device_id", "")))
        current = self.current_session_state()
        buffer = str(getattr(state, "recent_output_buffer", "") or "")
        return {
            "session_id": state.tab_id,
            "device_id": state.device_id,
            "device_name": getattr(device, "name", state.device_id),
            "title": state.title,
            "protocol": self._ai_session_protocol(state),
            "status": self._ai_session_status(state),
            "connected": bool(getattr(state.session, "is_connected", False)),
            "connecting": bool(getattr(state, "connecting", False)),
            "current": current is state,
            "host": state.host,
            "port": state.port,
            "output_cursor": int(getattr(state, "output_cursor", len(buffer))),
            "status_message": str(getattr(state, "status_text", "") or ""),
        }

    def _ai_session_summaries(self, *, device_id: str = "") -> list[dict[str, Any]]:
        states = list(getattr(self, "session_tabs_by_id", {}).values())
        if device_id:
            states = [
                state for state in states
                if str(getattr(state, "device_id", "")) == device_id
            ]
        return [self._ai_session_summary(state) for state in states]

    @staticmethod
    def _ai_failure(
        action: AiDeviceAction,
        code: str,
        message: str,
        *,
        http_status: int = 409,
        data: dict[str, Any] | None = None,
    ) -> AiDeviceToolResult:
        return AiDeviceToolResult(
            action,
            ok=False,
            message=message,
            data=data or {},
            error_code=code,
            http_status=http_status,
        )

    def _ai_resolve_session(
        self,
        action: AiDeviceAction,
        *,
        require_connected: bool = False,
    ) -> tuple[Any | None, AiDeviceToolResult | None]:
        session_id = str(action.params.get("session_id") or "")
        device_id = action.device_id or str(action.params.get("device_id") or "")
        states = list(getattr(self, "session_tabs_by_id", {}).values())
        if session_id:
            state = getattr(self, "session_tabs_by_id", {}).get(session_id)
            if state is None or (
                device_id and str(getattr(state, "device_id", "")) != device_id
            ):
                return None, self._ai_failure(
                    action,
                    "session_not_found",
                    f"未找到终端会话: {session_id}",
                    http_status=404,
                )
        else:
            matches = [
                state for state in states
                if str(getattr(state, "device_id", "")) == device_id
            ]
            if not matches:
                return None, self._ai_failure(
                    action,
                    "session_not_found",
                    f"设备没有打开的终端: {device_id}",
                    http_status=404,
                )
            if len(matches) > 1:
                return None, self._ai_failure(
                    action,
                    "ambiguous_session",
                    f"设备存在 {len(matches)} 个会话，请指定 session_id。",
                    data={
                        "sessions": [
                            self._ai_session_summary(candidate)
                            for candidate in matches
                        ]
                    },
                )
            state = matches[0]
        if require_connected and not bool(
            getattr(state.session, "is_connected", False)
        ):
            return None, self._ai_failure(
                action,
                "session_not_connected",
                f"会话尚未连接: {state.tab_id}",
                data={"session": self._ai_session_summary(state)},
            )
        return state, None

    def _ai_open_managed_session(self, action: AiDeviceAction) -> AiDeviceToolResult:
        device = self._ai_device(action.device_id)
        if device is None:
            return self._ai_failure(
                action,
                "device_not_found",
                f"未找到设备: {action.device_id}",
                http_status=404,
            )
        protocol = str(action.params.get("protocol") or "auto").casefold()
        simulated = bool(
            getattr(self, "is_simulated_device", lambda _device: False)(device)
        )
        if protocol == "auto":
            if simulated:
                protocol = "simulated"
            elif device.telnet_ip.strip():
                protocol = "telnet"
            elif device.ssh_ip.strip():
                protocol = "ssh"
            elif device.serial_ip.strip():
                protocol = "serial"
        supported = {
            "simulated": simulated,
            "telnet": bool(device.telnet_ip.strip()) and not simulated,
            "ssh": bool(device.ssh_ip.strip()) and not simulated,
            "serial": bool(device.serial_ip.strip()) and not simulated,
        }
        if protocol not in supported or not supported[protocol]:
            return self._ai_failure(
                action,
                "unsupported_protocol",
                f"设备 {device.id} 不支持协议: {protocol}",
                http_status=400,
                data={
                    "supported_protocols": [
                        name for name, available in supported.items() if available
                    ]
                },
            )
        existing = [
            state
            for state in getattr(self, "session_tabs_by_id", {}).values()
            if state.device_id == device.id
            and self._ai_session_protocol(state) == protocol
        ]
        if existing:
            state = next(
                (
                    candidate for candidate in existing
                    if bool(getattr(candidate.session, "is_connected", False))
                ),
                existing[0],
            )
            if self._ai_session_status(state) == "disconnected":
                self.reconnect_session_tab(state.tab_id)
            return AiDeviceToolResult(
                action,
                ok=True,
                message=f"已复用终端会话: {state.title}",
                data={"session": self._ai_session_summary(state), "reused": True},
            )

        if protocol == "simulated":
            state = self.ensure_session_tab(
                kind="simulated",
                device=device,
                host="localhost",
                port=0,
                username="sim",
                password="",
            )
        elif protocol == "telnet":
            username, password = self.session_telnet_credentials(device)
            state = self.ensure_session_tab(
                kind="device",
                device=device,
                host=device.telnet_ip.strip(),
                port=device.telnet_port,
                username=username,
                password=password,
            ) if username and password else None
        elif protocol == "ssh":
            username, password = self.session_ssh_credentials(device)
            state = self.ensure_session_tab(
                kind="linux",
                device=device,
                host=device.ssh_ip.strip(),
                port=device.ssh_port,
                username=username,
                password=password,
                credential_candidates=self.linux_ssh_credential_candidates(
                    device,
                    username,
                    password,
                ),
            ) if username and password else None
        else:
            temporary = bool(
                getattr(self, "is_temporary_device", lambda _device: False)(device)
            )
            occupied = bool(
                getattr(self, "is_my_occupied_device", lambda _device: False)(device)
            )
            if not temporary and not occupied:
                return self._ai_failure(
                    action,
                    "session_open_failed",
                    "串口连接需要先占用目标设备。",
                )
            username, password = self.session_serial_credentials(device)
            credentials_ready = bool(password) if temporary else bool(
                username and password
            )
            state = self.ensure_session_tab(
                kind="serial",
                device=device,
                host=device.serial_ip.strip(),
                port=device.serial_port,
                username=username,
                password=password,
            ) if credentials_ready else None
        if state is None:
            return self._ai_failure(
                action,
                "session_open_failed",
                f"无法创建 {protocol} 会话，请检查地址和凭据配置。",
            )
        return AiDeviceToolResult(
            action,
            ok=True,
            message=f"已创建终端会话: {state.title}",
            data={"session": self._ai_session_summary(state), "reused": False},
        )

    def _ai_session_for_device(self, device_id: str) -> Any | None:
        states = [
            state for state in getattr(self, "session_tabs_by_id", {}).values()
            if getattr(state, "device_id", "") == device_id
        ]
        if not states:
            return None
        connected = [state for state in states if getattr(state.session, "is_connected", False)]
        return connected[0] if connected else states[0]

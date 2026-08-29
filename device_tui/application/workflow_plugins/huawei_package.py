"""Huawei VRP package replacement as a framework Workflow Provider.

The provider declares business states and recovery options.  Huawei command
syntax stays in the device adapter/legacy upgrade driver and is not used by
the generic runtime.
"""

from __future__ import annotations

import re
from dataclasses import asdict
from pathlib import PurePosixPath
from typing import Any

from device_tui.application.workflows.events import Event
from device_tui.application.workflows.models import (
    ActionSpec,
    Expectation,
    InteractionPolicy,
    Option,
    ReconcilePolicy,
    RetryPolicy,
    StateNode,
    WorkflowDefinition,
)
from device_tui.infrastructure.vendor_adapters.huawei_vrp.commands import HuaweiVrpCommandSet


class HuaweiVrpPackageUpgradeProvider:
    id = "network.package_upgrade"
    version = "1"

    def build(self, inputs: dict[str, Any]) -> WorkflowDefinition:
        package = str(inputs.get("package_ref") or "").strip()
        expected_version = str(inputs.get("expected_version") or "").strip()
        activation_policy = str(inputs.get("activation_policy") or "reboot").casefold()
        auto_reboot = bool(inputs.get("auto_reboot", True))
        package_source = str(inputs.get("package_source") or "local").casefold()
        topology_policy = str(inputs.get("topology_policy") or "auto").casefold()
        cleanup_policy = str(inputs.get("cleanup_policy") or "never").casefold()
        recovery_protocol = str(inputs.get("recovery_protocol") or "same").casefold()
        transfer_protocol = str(inputs.get("transfer_protocol") or "ftp").casefold()
        if not package:
            raise ValueError("package_ref is required")
        if activation_policy not in {"stage_only", "reboot"}:
            raise ValueError("activation_policy must be stage_only or reboot")
        if package_source not in {"local", "device"}:
            raise ValueError("package_source must be local or device")
        if topology_policy not in {"auto", "single", "required"}:
            raise ValueError("topology_policy must be auto, single, or required")
        if cleanup_policy not in {"never", "auto"}:
            raise ValueError("cleanup_policy must be never or auto")
        if recovery_protocol not in {"", "same", "auto", "ssh", "telnet", "serial"}:
            raise ValueError("recovery_protocol must be same, auto, ssh, telnet, or serial")
        if transfer_protocol not in {"ftp", "sftp"}:
            raise ValueError("transfer_protocol must be ftp or sftp")
        retry = RetryPolicy(max_attempts=2, retryable_classes=("transient", "timeout", "connection"))
        retry_three = RetryPolicy(max_attempts=3, retryable_classes=("transient", "timeout", "connection"))
        transfer_options = (
            Option("retry_transfer", "retry", "重试传输", "先按 Reconcile 结果确认没有完整文件。"),
            Option("reconnect_transfer", "reconnect", "重连后重试", "重建 FTP 子会话后重新确认文件状态。"),
            Option("abort_transfer", "abort", "终止流程", risk="high", requires_reason=True),
        )
        startup_options = (
            Option("retry_startup", "retry", "重试设置启动项"),
            Option("rollback_startup", "rollback", "恢复原启动项", risk="critical", allowed_actors=("human", "rule"), requires_reason=True, next_state="rollback"),
            Option("abort_startup", "abort", "终止流程", risk="high", requires_reason=True),
        ) if activation_policy == "reboot" else (
            Option("retry_startup", "retry", "重试设置启动项"),
            Option("abort_startup", "abort", "终止流程", risk="high", requires_reason=True),
        )
        verification_options = (
            Option("retry_verify", "retry", "重新校验"),
            Option("rollback", "rollback", "回滚到升级前版本", risk="critical", allowed_actors=("human", "rule"), requires_reason=True, next_state="rollback"),
            Option("abort_verify", "abort", "终止流程", risk="high", requires_reason=True),
        )
        rollback_options = (
            Option("retry_rollback", "retry", "重新尝试回滚", risk="critical", allowed_actors=("human", "rule"), requires_reason=True),
            Option("abort_rollback", "abort", "终止流程", risk="critical", requires_reason=True),
        )
        storage_options = (
            Option("retry_storage", "retry", "重试存储操作"),
            Option("abort_storage", "abort", "终止流程", risk="high", requires_reason=True),
        )
        topology_options = (
            Option("retry_topology", "retry", "重新探测设备拓扑"),
            Option("continue_single", "continue", "按单主控继续", risk="high", allowed_actors=("human", "rule"), requires_reason=True, next_state="cleanup"),
            Option("abort_topology", "abort", "终止流程", risk="high", requires_reason=True),
        ) if topology_policy == "auto" else (
            Option("retry_topology", "retry", "重新探测设备拓扑"),
            Option("abort_topology", "abort", "终止流程", risk="high", requires_reason=True),
        )
        local_transfer = package_source == "local"
        validation_params: dict[str, Any] = {"fact": "validation"}
        validation_commands = inputs.get("validation_commands")
        if isinstance(validation_commands, (tuple, list)) and validation_commands:
            validation_params["commands"] = tuple(str(item) for item in validation_commands)
        has_validation = bool(validation_params.get("commands"))
        version_state: tuple[StateNode, ...] = ()
        if activation_policy == "reboot":
            version_state = (
                StateNode(
                    id="verify_version",
                    label="校验启动版本",
                    description="使用 display startup 确认设备当前运行的是目标系统包。",
                    action=ActionSpec(
                        id="verify_version",
                        operation="device.verify_version",
                        params={
                            "_framework_activity": True,
                            "fact": "startup_package",
                            "expected": package,
                            "commands": (HuaweiVrpCommandSet.startup_query(),),
                        },
                        expectations=(Expectation("huawei.startup.package.match", timeout_seconds=90),),
                        timeout_seconds=120,
                    ),
                    next_state="validation" if has_validation else "complete",
                    decision_options=verification_options,
                ),
            )
        validation_state: tuple[StateNode, ...] = ()
        if has_validation:
            validation_state = (
                StateNode(
                    id="validation",
                    label="最终验证",
                    description="执行调用方明确提供的升级后验证命令。",
                    action=ActionSpec(
                        id="validation",
                        operation="device.verify",
                        params=validation_params,
                        expectations=(Expectation("huawei.validation.passed", timeout_seconds=90),),
                        timeout_seconds=120,
                    ),
                    next_state="complete",
                ),
            )
        states = [
            StateNode(
                id="precheck",
                label="设备预检",
                description="在当前管理 CLI 上采集版本、启动项和存储事实。",
                action=ActionSpec(
                    id="precheck",
                    operation="device.probe",
                    params={
                        # Reachability is checked by the session layer. This
                        # action only runs the device-side read-only probes.
                        "probes": ("version", "startup", "storage", "topology"),
                        "package": package,
                        "package_source": package_source,
                        "topology_policy": topology_policy,
                        "master_storage": str(inputs.get("master_storage") or "flash:/"),
                        "slave_storage": str(inputs.get("slave_storage") or "slave#flash:/"),
                    },
                    expectations=(Expectation("huawei.cli.ready"), Expectation("huawei.device.facts.collected")),
                    timeout_seconds=120,
                ),
                decision_options=topology_options,
                next_state="cleanup",
            ),
        ]
        states.extend((
            StateNode(
                id="cleanup",
                label="检查并清理存储",
                description="按策略确认空间并清理未使用的软件包。",
                action=ActionSpec(
                    id="cleanup",
                    operation="device.storage.cleanup",
                    params={
                        "_framework_activity": True,
                        "package": package,
                        "package_source": package_source,
                        "include_slave": topology_policy != "single",
                        "standby_required": topology_policy == "required",
                        "auto_delete_old_packages": cleanup_policy == "auto",
                        "master_storage": str(inputs.get("master_storage") or "flash:/"),
                        "slave_storage": str(inputs.get("slave_storage") or "slave#flash:/"),
                        "driver_id": str(inputs.get("driver_id") or "auto"),
                    },
                    expectations=(Expectation("huawei.storage.cleaned", timeout_seconds=120),),
                    timeout_seconds=150,
                    retry_policy=retry,
                ),
                next_state="transfer" if local_transfer else "verify_package",
                decision_options=storage_options,
            ),
        ))
        if local_transfer:
            package_name = PurePosixPath(package.replace("\\", "/")).name
            master_storage = str(inputs.get("master_storage") or "flash:/")
            transfer_profile = HuaweiVrpCommandSet().transfer_profile(transfer_protocol)
            states.append(StateNode(
                id="transfer",
                label="传输系统包",
                description="发送 GET 并持续确认传输已开始且存在进度。",
                action=ActionSpec(
                    id="transfer",
                    operation="file.transfer",
                    params={
                        "_framework_activity": True,
                        "source": package,
                        "source_path": package,
                        "destination_path": HuaweiVrpCommandSet.package_path(master_storage, package_name),
                        "direction": "upload",
                        "transfer_protocol": transfer_protocol,
                        "command_mode": "vrp",
                        "terminal_environment": "vrp",
                        "interaction_profile": asdict(transfer_profile),
                        "skip_if_present": True,
                        "package": package,
                        "temporary_suffix": ".part",
                        "package_source": package_source,
                        "master_storage": master_storage,
                        "include_slave": topology_policy != "single",
                        "standby_required": topology_policy == "required",
                        "auto_delete_old_packages": cleanup_policy == "auto",
                    },
                    expectations=(
                        Expectation("activity.preconditions.checked", timeout_seconds=5),
                        Expectation("transfer.started", timeout_seconds=60),
                        Expectation("transfer.completed", timeout_seconds=3600, idle_timeout_seconds=90, progress=True),
                    ),
                    timeout_seconds=3600,
                    retry_policy=retry,
                    reconcile=ReconcilePolicy(
                        provider="huawei.reconcile.transfer",
                        probes=("dir", "size", "hash"),
                        on_classification={"confirmed_success": "continue", "confirmed_not_started": "retry"},
                    ),
                ),
                next_state="verify_package",
                decision_options=transfer_options,
            ))
        states.extend((
            StateNode(
                id="verify_package",
                label="校验系统包",
                description="确认主控上的目标系统包完整可用。",
                action=ActionSpec(
                    id="verify_package",
                    operation="device.verify_artifact",
                    params={
                        "_framework_activity": True,
                        "fact": "package",
                        "expected": package,
                    },
                    expectations=(Expectation("huawei.package.verified", timeout_seconds=60),),
                    timeout_seconds=90,
                ),
                next_state="sync_standby",
            ),
            StateNode(
                id="sync_standby",
                label="同步备控系统包",
                description="根据拓扑策略同步并校验备控上的系统包。",
                action=ActionSpec(
                    id="sync_standby",
                    operation="device.storage.sync",
                    params={
                        "_framework_activity": True,
                        "package": package,
                        "master_storage": str(inputs.get("master_storage") or "flash:/"),
                        "slave_storage": str(inputs.get("slave_storage") or "slave#flash:/"),
                        "driver_id": str(inputs.get("driver_id") or "auto"),
                    },
                    expectations=(Expectation("huawei.storage.synced", timeout_seconds=180),),
                    timeout_seconds=210,
                    retry_policy=retry,
                ),
                next_state="configure_startup",
                decision_options=storage_options,
            ),
            StateNode(
                id="configure_startup",
                label="设置启动项",
                description="完成设备侧确认交互，并回读下一次启动项确认目标系统包已生效。",
                action=ActionSpec(
                    id="configure_startup",
                    operation="device.startup.configure",
                    params={
                        "_framework_activity": True,
                        "package": package,
                        "master_storage": str(inputs.get("master_storage") or "flash:/"),
                        "slave_storage": str(inputs.get("slave_storage") or "slave#flash:/"),
                        "driver_id": str(inputs.get("driver_id") or "auto"),
                    },
                    expectations=(
                        Expectation("framework.action.sent", timeout_seconds=5),
                        Expectation("huawei.startup.command.completed", timeout_seconds=90),
                        Expectation("huawei.startup.verified", timeout_seconds=120),
                    ),
                    timeout_seconds=120,
                    risk="high",
                    reconcile=ReconcilePolicy(
                        provider="huawei.reconcile.startup",
                        probes=("startup",),
                        on_classification={"confirmed_success": "continue"},
                    ),
                ),
                next_state=("reboot" if auto_reboot else "reboot_approval") if activation_policy == "reboot" else "complete",
                decision_options=startup_options,
            ),
        ))
        if activation_policy == "reboot":
            states.extend((
                StateNode(
                    id="reboot_approval",
                    label="等待重启决策",
                    description="启动项已设置，等待受约束的重启或终止决策。",
                    decision_options=(
                        Option("approve_reboot", "continue", "批准重启", risk="critical", allowed_actors=("human", "rule"), next_state="reboot"),
                        Option("abort_reboot", "abort", "终止流程", risk="critical", requires_reason=True),
                    ),
                ),
                StateNode(
                    id="reboot",
                    label="重启设备",
                    description="处理设备侧确认交互并确认重启已发起。",
                    action=ActionSpec(
                        id="reboot",
                        operation="device.reboot",
                        params={"_framework_activity": True},
                        # The terminal plan reports this only after it observes
                        # the confirmation/disconnect boundary, not at send().
                        expectations=(Expectation("huawei.reboot.started", timeout_seconds=210),),
                        timeout_seconds=210,
                        retry_policy=RetryPolicy(max_attempts=1),
                        risk="critical",
                        interaction=InteractionPolicy(confirmations={"confirmation_prompt": "y"}),
                        reconcile=ReconcilePolicy(
                            provider="huawei.reconcile.reboot",
                            probes=("ping", "ssh", "cli"),
                            on_classification={"confirmed_success": "continue", "confirmed_not_started": "retry"},
                        ),
                    ),
                    next_state="wait_online",
                    decision_options=(
                        Option("retry_reboot", "retry", "重新执行重启", risk="critical", allowed_actors=("human", "rule"), requires_reason=True),
                        Option("abort_reboot", "abort", "终止流程", risk="critical", requires_reason=True),
                    ),
                ),
                StateNode(
                    id="wait_online",
                    label="等待管理面恢复",
                    description="重建管理会话并确认 CLI 已可执行。",
                    action=ActionSpec(
                        id="wait_online",
                        operation="device.wait_online",
                        params={
                            "_framework_activity": True,
                            "phases": ("session", "cli"),
                            "recovery_protocol": recovery_protocol,
                        },
                        expectations=(Expectation("huawei.cli.ready", timeout_seconds=600),),
                        timeout_seconds=600,
                        retry_policy=retry_three,
                        reconcile=ReconcilePolicy(provider="huawei.reconcile.online", probes=("ping", "ssh", "cli")),
                    ),
                    next_state="verify_version",
                    decision_options=(
                        Option("reconnect", "reconnect", "重连管理通道"),
                        Option("abort_online", "abort", "终止流程", risk="high", requires_reason=True),
                    ),
                ),
                *version_state,
                *validation_state,
                StateNode(
                    id="rollback",
                    label="回滚",
                    description="恢复升级前启动项并确认设备状态。",
                    action=ActionSpec(
                    id="rollback",
                        operation="device.startup.rollback",
                        params={
                            "_framework_activity": True,
                            "package": package,
                            "rollback_source": "precheck.startup.current_system",
                        },
                        expectations=(Expectation("huawei.rollback.verified", timeout_seconds=600),),
                        timeout_seconds=600,
                        retry_policy=RetryPolicy(max_attempts=1),
                        risk="critical",
                        reconcile=ReconcilePolicy(
                            provider="huawei.reconcile.rollback",
                            probes=("startup", "version", "ping", "ssh", "cli"),
                            on_classification={"confirmed_success": "continue"},
                        ),
                    ),
                    next_state="complete",
                    decision_options=rollback_options,
                ),
            ))
        states.append(StateNode(id="complete", terminal=True, label="完成", description="Workflow 已完成。"))
        return WorkflowDefinition(
            id=self.id,
            version=self.version,
            start_state="precheck",
            required_capabilities=("huawei.vrp",) + (("file.transfer",) if local_transfer else ()) + (("device.reboot",) if activation_policy == "reboot" else ()),
            input_schema={
                "type": "object",
                "required": ["package_ref"],
                "properties": {
                    "package_ref": {"type": "string"},
                    "expected_version": {"type": "string"},
                    "activation_policy": {"type": "string", "enum": ["stage_only", "reboot"], "default": "reboot"},
                    "auto_reboot": {"type": "boolean", "default": True},
                    "transfer_protocol": {"type": "string", "enum": ["ftp", "sftp"], "default": "ftp"},
                },
            },
            metadata={"vendor": "Huawei", "platform": "VRP", "workflow_family": "package_upgrade"},
            states=tuple(states),
        )


class HuaweiVrpWorkflowAdapter:
    """Framework adapter facade over the existing Huawei VRP upgrade driver."""

    id = "huawei-vrp"

    def matches(self, facts: dict[str, Any]) -> bool:
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

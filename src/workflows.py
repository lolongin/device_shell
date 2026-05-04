from __future__ import annotations

import shlex
from dataclasses import dataclass, field

try:
    from .session_protocol import SessionTarget
except ImportError:
    from session_protocol import SessionTarget


class WorkflowParseError(Exception):
    """Raised when local workflow input cannot be parsed."""


@dataclass(slots=True)
class WorkflowRequest:
    name: str
    args: list[str] = field(default_factory=list)


@dataclass(slots=True)
class WorkflowStep:
    target: SessionTarget
    command: str
    label: str
    stop_on_error: bool = True


def parse_workflow_input(text: str) -> WorkflowRequest:
    stripped = text.strip()
    if not stripped.startswith("/"):
        raise WorkflowParseError("Workflow commands must start with '/'.")

    try:
        tokens = shlex.split(stripped[1:])
    except ValueError as exc:
        raise WorkflowParseError(str(exc)) from exc

    if not tokens:
        raise WorkflowParseError("Workflow command is empty.")

    return WorkflowRequest(name=tokens[0], args=tokens[1:])


def build_workflow_steps(request: WorkflowRequest) -> list[WorkflowStep]:
    if request.name == "collect_log":
        return [
            WorkflowStep(
                target="device",
                command="screen-length 0 temporary",
                label="Disable paging on device",
            ),
            WorkflowStep(
                target="device",
                command="display logbuffer",
                label="Collect device logbuffer",
            ),
            WorkflowStep(
                target="linux",
                command="mkdir -p /tmp/huawei_logs",
                label="Prepare Linux log directory",
            ),
            WorkflowStep(
                target="linux",
                command="echo collect_log placeholder > /tmp/huawei_logs/collect_log.txt",
                label="Record workflow marker on Linux",
            ),
        ]

    if request.name == "change_cc":
        cc_value = request.args[0] if request.args else "<cc-value>"
        return [
            WorkflowStep(
                target="linux",
                command=f"echo precheck for change_cc {cc_value}",
                label="Run Linux precheck",
            ),
            WorkflowStep(
                target="device",
                command="system-view",
                label="Enter device configuration mode",
            ),
            WorkflowStep(
                target="device",
                command=f"# TODO apply change_cc {cc_value}",
                label="Apply placeholder CC change on device",
            ),
            WorkflowStep(
                target="device",
                command="return",
                label="Return to user view",
            ),
            WorkflowStep(
                target="linux",
                command=f"echo change_cc {cc_value} placeholder finished",
                label="Record workflow result on Linux",
            ),
        ]

    raise WorkflowParseError(f"Unknown workflow command: /{request.name}")


from __future__ import annotations

from dataclasses import dataclass

try:
    from .session_protocol import CommandSession, OutputEmitter, SessionTarget, StatusEmitter
    from .workflows import WorkflowRequest, WorkflowStep, build_workflow_steps
except ImportError:
    from session_protocol import CommandSession, OutputEmitter, SessionTarget, StatusEmitter
    from workflows import WorkflowRequest, WorkflowStep, build_workflow_steps


class WorkflowExecutionError(Exception):
    """Raised when a workflow cannot complete successfully."""


@dataclass(slots=True)
class WorkflowContext:
    linux: CommandSession
    device: CommandSession
    emit_output: OutputEmitter
    emit_status: StatusEmitter


class WorkflowRunner:
    def __init__(self, context: WorkflowContext) -> None:
        self.context = context

    async def run(self, request: WorkflowRequest) -> None:
        steps = build_workflow_steps(request)
        self.context.emit_status(f"Workflow: /{request.name}")
        self.context.emit_output(f"\nstart /{request.name}\n")

        for index, step in enumerate(steps, start=1):
            session = self._session_for_target(step.target)
            if not session.is_connected:
                message = f"Workflow step {index} requires connected target '{step.target}'."
                self.context.emit_output(f"error {message}\n")
                raise WorkflowExecutionError(message)

            self.context.emit_output(f"step {index}/{len(steps)} {step.target} :: {step.label}\n")
            try:
                await session.send_command(step.command)
            except Exception as exc:
                message = f"Workflow step {index} failed on '{step.target}': {exc}"
                self.context.emit_output(f"error {message}\n")
                if step.stop_on_error:
                    raise WorkflowExecutionError(message) from exc

        self.context.emit_output(f"done /{request.name}\n")
        self.context.emit_status("Workflow idle")

    def _session_for_target(self, target: SessionTarget) -> CommandSession:
        if target == "linux":
            return self.context.linux
        return self.context.device

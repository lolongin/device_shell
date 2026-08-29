"""Plugin contracts and registries for workflow and device extensions."""

from __future__ import annotations

from typing import Any, Protocol

from .activity import (
    ActivityContext,
    ActivityDefinition,
    ActivityHandler,
    ActivityInvocation,
    ActivityResult,
)
from .events import Event
from .models import ActionResult, ActionSpec, ReconcileResult, WorkflowDefinition, WorkflowRun


class ActionHandler(Protocol):
    operation: str

    async def execute(
        self,
        action: ActionSpec,
        run: WorkflowRun,
        emit: Any,
    ) -> ActionResult: ...


class ReconcileProvider(Protocol):
    id: str

    async def reconcile(
        self,
        action: ActionSpec,
        run: WorkflowRun,
        reason: str,
        emit: Any,
    ) -> ReconcileResult: ...


class DeviceAdapter(Protocol):
    id: str

    def matches(self, facts: dict[str, Any]) -> bool: ...
    def capabilities(self) -> set[str]: ...
    def parse_output(self, output: str, *, run_id: str, action_id: str) -> tuple[Event, ...]: ...


class DeviceVendorAdapter(Protocol):
    """Vendor port used by generic device Activities.

    Command syntax, output parsing, and vendor-specific read-back checks stay
    behind this port.  The Activity runtime only sees structured results.
    """

    id: str

    async def execute_activity(
        self,
        activity_id: str,
        invocation: ActivityInvocation,
        context: ActivityContext,
        report: Any,
    ) -> ActivityResult: ...

    async def cancel_activity(
        self,
        activity_id: str,
        invocation: ActivityInvocation,
        context: ActivityContext,
    ) -> None: ...


class WorkflowProvider(Protocol):
    id: str
    version: str

    def build(self, inputs: dict[str, Any]) -> WorkflowDefinition: ...


class _Registry:
    def __init__(self) -> None:
        self._items: dict[str, Any] = {}

    def register(self, item: Any, *, item_id: str | None = None) -> None:
        key = str(item_id or getattr(item, "id", "") or getattr(item, "operation", "")).strip()
        if not key:
            raise ValueError("registered item id is required")
        if key in self._items:
            raise ValueError(f"item already registered: {key}")
        self._items[key] = item

    def get(self, item_id: str) -> Any:
        try:
            return self._items[item_id]
        except KeyError as exc:
            raise KeyError(f"unknown registered item: {item_id}") from exc

    def list(self) -> tuple[Any, ...]:
        return tuple(self._items.values())


class WorkflowRegistry(_Registry):
    def register(self, provider: WorkflowProvider, *, item_id: str | None = None) -> None:
        super().register(provider, item_id=item_id or provider.id)

    def build(self, workflow_id: str, inputs: dict[str, Any]) -> WorkflowDefinition:
        definition = self.get(workflow_id).build(dict(inputs))
        definition.validate()
        return definition


class AdapterRegistry(_Registry):
    def resolve(self, facts: dict[str, Any], required_capabilities: set[str] | None = None) -> DeviceAdapter:
        required = set(required_capabilities or ())
        matches = [item for item in self.list() if item.matches(facts) and required <= item.capabilities()]
        if len(matches) != 1:
            raise LookupError(f"expected exactly one device adapter, found {len(matches)}")
        return matches[0]


class ActionRegistry(_Registry):
    def resolve(self, operation: str) -> ActionHandler:
        return self.get(operation)


class ActivityRegistry(_Registry):
    """Registry for versioned Activity contracts during migration."""

    def register_definition(self, definition: ActivityDefinition) -> None:
        definition.validate()
        self.register(definition, item_id=f"{definition.id}:{definition.version}")

    def register_handler(self, handler: ActivityHandler, *, activity_id: str | None = None) -> None:
        self.register(handler, item_id=activity_id or handler.activity_id)

    def resolve_definition(self, activity_id: str, version: str = "1") -> ActivityDefinition:
        return self.get(f"{activity_id}:{version}")

    def resolve_handler(self, activity_id: str) -> ActivityHandler:
        return self.get(activity_id)


class ReconcileRegistry(_Registry):
    def resolve(self, provider_id: str) -> ReconcileProvider:
        return self.get(provider_id)

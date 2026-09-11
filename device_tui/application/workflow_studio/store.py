from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime
from typing import Protocol

from .models import WorkflowDraft, WorkflowVersion


class WorkflowDefinitionStore(Protocol):
    def create(self, draft: WorkflowDraft) -> WorkflowDraft: ...
    def save(self, draft: WorkflowDraft) -> WorkflowDraft: ...
    def get(self, workflow_id: str, version: int | str | None = None) -> WorkflowDraft | WorkflowVersion: ...
    def list(self, *, limit: int = 500) -> list[WorkflowDraft]: ...
    def delete(self, workflow_id: str, version: int | str | None = None) -> None: ...
    def publish(self, workflow_id: str) -> WorkflowVersion: ...


class MemoryWorkflowDefinitionStore:
    def __init__(self) -> None:
        self._drafts: dict[str, WorkflowDraft] = {}
        self._versions: dict[str, dict[int, WorkflowVersion]] = {}
        self._references: set[tuple[str, int]] = set()

    def create(self, draft: WorkflowDraft) -> WorkflowDraft:
        if draft.id in self._drafts:
            raise ValueError(f"workflow already exists: {draft.id}")
        self._drafts[draft.id] = deepcopy(draft)
        return deepcopy(draft)

    def save(self, draft: WorkflowDraft) -> WorkflowDraft:
        if draft.id not in self._drafts:
            raise KeyError(f"workflow not found: {draft.id}")
        self._drafts[draft.id] = deepcopy(draft)
        return deepcopy(draft)

    def get(self, workflow_id: str, version: int | str | None = None) -> WorkflowDraft | WorkflowVersion:
        if version is None or version == "draft":
            if workflow_id not in self._drafts:
                raise KeyError(f"workflow not found: {workflow_id}")
            return deepcopy(self._drafts[workflow_id])
        try:
            result = self._versions[workflow_id][int(version)]
        except (KeyError, ValueError):
            raise KeyError(f"workflow version not found: {workflow_id}@{version}") from None
        return deepcopy(result)

    def list(self, *, limit: int = 500) -> list[WorkflowDraft]:
        return [deepcopy(item) for item in list(self._drafts.values())[: max(0, limit)]]

    def delete(self, workflow_id: str, version: int | str | None = None) -> None:
        if version is None or version == "draft":
            if workflow_id not in self._drafts:
                raise KeyError(f"workflow not found: {workflow_id}")
            self._drafts.pop(workflow_id)
            return
        key = (workflow_id, int(version))
        if key in self._references:
            raise ValueError(f"published workflow version is referenced: {workflow_id}@{version}")
        versions = self._versions.get(workflow_id, {})
        if int(version) not in versions:
            raise KeyError(f"workflow version not found: {workflow_id}@{version}")
        versions.pop(int(version))

    def publish(self, workflow_id: str) -> WorkflowVersion:
        draft = self.get(workflow_id)
        versions = self._versions.setdefault(workflow_id, {})
        number = max(versions, default=0) + 1
        version = WorkflowVersion(workflow_id, number, draft.name, draft.inputs, draft.nodes, draft.edges, datetime.now(UTC).isoformat())
        versions[number] = version
        return deepcopy(version)

    def mark_referenced(self, workflow_id: str, version: int | str) -> None:
        self._references.add((workflow_id, int(version)))


__all__ = ["WorkflowDefinitionStore", "MemoryWorkflowDefinitionStore"]

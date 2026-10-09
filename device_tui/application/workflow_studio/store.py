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
    def delete_preserving_references(self, workflow_id: str) -> None: ...
    def publish(self, workflow_id: str) -> WorkflowVersion: ...
    def list_versions(self, workflow_id: str) -> list[WorkflowVersion]: ...
    def is_referenced(self, workflow_id: str, version: int | str) -> bool: ...
    def referenced_versions(self, workflow_id: str) -> set[int]: ...
    def list_published(self, *, latest_only: bool = True, limit: int = 500) -> list[WorkflowVersion]: ...


class MemoryWorkflowDefinitionStore:
    def __init__(self) -> None:
        self._drafts: dict[str, WorkflowDraft] = {}
        self._versions: dict[str, dict[int, WorkflowVersion]] = {}
        self._deleted_versions: dict[str, set[int]] = {}
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
        if int(version) in self._deleted_versions.get(workflow_id, set()):
            raise KeyError(f"workflow version not found: {workflow_id}@{version}")
        return deepcopy(result)

    def list(self, *, limit: int = 500) -> list[WorkflowDraft]:
        return [deepcopy(item) for item in list(self._drafts.values())[: max(0, limit)]]

    def delete(self, workflow_id: str, version: int | str | None = None) -> None:
        if version is None or version == "draft":
            if workflow_id not in self._drafts:
                raise KeyError(f"workflow not found: {workflow_id}")
            if any(key[0] == workflow_id for key in self._references):
                raise ValueError(f"workflow has referenced published versions: {workflow_id}")
            self._drafts.pop(workflow_id)
            self._versions.pop(workflow_id, None)
            self._deleted_versions.pop(workflow_id, None)
            return
        versions = self._versions.get(workflow_id, {})
        if int(version) not in versions:
            raise KeyError(f"workflow version not found: {workflow_id}@{version}")
        if int(version) in self._deleted_versions.get(workflow_id, set()):
            raise KeyError(f"workflow version not found: {workflow_id}@{version}")
        self._deleted_versions.setdefault(workflow_id, set()).add(int(version))

    def delete_preserving_references(self, workflow_id: str) -> None:
        """Remove the editable workflow while retaining referenced history markers."""
        if workflow_id not in self._drafts:
            raise KeyError(f"workflow not found: {workflow_id}")
        self._drafts.pop(workflow_id)
        versions = self._versions.get(workflow_id, {})
        if versions:
            self._deleted_versions[workflow_id] = set(versions)
        else:
            self._versions.pop(workflow_id, None)
            self._deleted_versions.pop(workflow_id, None)

    def publish(self, workflow_id: str) -> WorkflowVersion:
        draft = self.get(workflow_id)
        versions = self._versions.setdefault(workflow_id, {})
        number = max(versions, default=0) + 1
        version = WorkflowVersion(workflow_id=workflow_id, version=number, name=draft.name, inputs=draft.inputs, nodes=draft.nodes, edges=draft.edges, published_at=datetime.now(UTC).isoformat(), description=draft.description, outputs=draft.outputs, canvas_edges=draft.canvas_edges)
        versions[number] = version
        return deepcopy(version)

    def list_versions(self, workflow_id: str) -> list[WorkflowVersion]:
        deleted = self._deleted_versions.get(workflow_id, set())
        return [deepcopy(item) for number, item in sorted(self._versions.get(workflow_id, {}).items()) if number not in deleted]

    def is_referenced(self, workflow_id: str, version: int | str) -> bool:
        return (workflow_id, int(version)) in self._references

    def referenced_versions(self, workflow_id: str) -> set[int]:
        return {version for item_id, version in self._references if item_id == workflow_id}

    def list_published(self, *, latest_only: bool = True, limit: int = 500) -> list[WorkflowVersion]:
        if latest_only:
            versions = [items[max(number for number in items if number not in self._deleted_versions.get(workflow_id, set()))] for workflow_id, items in self._versions.items() if workflow_id in self._drafts and any(number not in self._deleted_versions.get(workflow_id, set()) for number in items)]
        else:
            versions = [item for workflow_id, items in self._versions.items() if workflow_id in self._drafts for number, item in items.items() if number not in self._deleted_versions.get(workflow_id, set())]
        versions.sort(key=lambda item: (item.published_at or "", item.workflow_id, int(item.version)), reverse=True)
        return [deepcopy(item) for item in versions[: max(0, limit)]]

    def mark_referenced(self, workflow_id: str, version: int | str) -> None:
        self._references.add((workflow_id, int(version)))


__all__ = ["WorkflowDefinitionStore", "MemoryWorkflowDefinitionStore"]

"""Application composition roots for assembling framework and plugins."""

from .workflows import (
    build_default_activity_executor,
    build_default_adapter_registry,
    build_default_workflow_registry,
)

__all__ = [
    "build_default_activity_executor",
    "build_default_adapter_registry",
    "build_default_workflow_registry",
]

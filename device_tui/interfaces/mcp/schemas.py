"""Discoverable MCP proposal schemas; execution policy remains in the backend."""

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ProposalModel(BaseModel):
    # Keep extension fields and legacy aliases available to the backend compiler.
    model_config = ConfigDict(extra="allow")


class PlanStepInput(ProposalModel):
    id: str = Field(description="Unique step ID within this plan")
    capability: str = Field(description="Capability action from workflow.list; do not invent names")
    params: dict[str, Any] = Field(default_factory=dict)
    depends_on: list[str] = Field(default_factory=list, description="IDs of prerequisite steps")
    retry_policy: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class WorkflowPlanInput(ProposalModel):
    objective: str = Field(description="Observable goal of the task")
    target: dict[str, str] = Field(description="Target with device_id and optional protocol")
    steps: list[PlanStepInput] = Field(description="Up to 50 capability steps; dependencies must form a DAG")
    plan_id: str = ""
    success_criteria: list[dict[str, Any]] = Field(default_factory=list)
    budget: dict[str, Any] = Field(default_factory=dict)
    parent_task_id: str = ""
    revision: int = 1
    metadata: dict[str, Any] = Field(default_factory=dict)


class DecisionActionInput(ProposalModel):
    name: str = Field(description="Action name from DecisionContext.available_actions")
    parameters: dict[str, Any] = Field(default_factory=dict)
    target_step: str = ""
    expected_revision: int | None = None
    risk: str = "normal"
    confirmation_required: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)

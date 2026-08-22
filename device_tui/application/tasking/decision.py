"""Decision boundary for human or agent supplied workflow decisions."""

from __future__ import annotations

from typing import Any, Protocol

from .models import DecisionRequest, DecisionResult


class DecisionEngine(Protocol):
    async def decide(self, request: DecisionRequest) -> DecisionResult: ...


class RuleDecisionEngine:
    """Small deterministic default; an LLM adapter can implement the protocol later."""

    async def decide(self, request: DecisionRequest) -> DecisionResult:
        params = request.step.params
        if "approved" in params:
            approved = bool(params["approved"])
        elif "when" in params and isinstance(params["when"], dict):
            condition = params["when"]
            key = str(condition.get("output_key") or "")
            expected = condition.get("equals", True)
            approved = bool(request.outputs.get(key) == expected)
        else:
            approved = bool(params.get("default", False))
        return DecisionResult(
            approved=approved,
            action=str(params.get("on_approved" if approved else "on_rejected") or ""),
            reason="rule decision",
            data={"step_id": request.step.id},
        )

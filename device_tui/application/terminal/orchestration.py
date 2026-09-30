"""Event-driven terminal interaction plans and per-session execution leases."""

from __future__ import annotations

from .execution_runner import TerminalExecutionRunner, TerminalStepResult
from .execution_coordinator import TerminalExecutionCoordinator
from .plan_models import (
    CONTROL_TEXT,
    DEFAULT_PAGINATION_MAX_MATCHES,
    MAX_MATCH_TEXT,
    MAX_PLAN_STEPS,
    MAX_STEP_OUTPUT_CHARS,
    ExpectStep,
    ResponseRule,
    SendStep,
    TerminalExecutionPlan,
    TerminalInput,
    TerminalPlanError,
    TerminalStep,
    WaitStateStep,
)





# Compatibility façade: parsing now lives in ``plan_parser`` while this module
# keeps the historical import path used by application adapters.
from .plan_parser import (
    build_batch_plan as build_batch_plan,
    parse_terminal_plan as parse_terminal_plan,
)

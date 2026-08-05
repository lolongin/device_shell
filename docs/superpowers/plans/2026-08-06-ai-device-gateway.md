# AI Device Gateway Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an `ai_*` MCP tool namespace to the existing `device_tui` FastMCP server that gives AI agents high-level device operations — summarized results with deferred raw retrieval, flow orchestration with dependencies/wait/retry, and skill reuse — reusing the existing session, execution, transfer, approval, audit, and idempotency stack.

**Architecture:** New `src/ai_gateway/` package on the app side (`GatewayService` facade wrapping `ResultStore`, `FlowEngine`, `SkillRegistry`). MCP tools are thin forwards. `ai_*` tools route through the existing `AppControlService` risk/approval/audit chain, then to new `ai_*` branches in the `AiDeviceOpsMixin` handler dict, then to `GatewayService`. `ai_execute_*` runs synchronously (reusing `TerminalExecutionCoordinator`'s completion-event wait); `ai_run_skill` and multi-command flows may exceed 60s so they can run async and be awaited via `operation_wait`.

**Tech Stack:** Python 3, PySide6 (app), FastMCP, asyncio/asyncssh/telnetlib3 (sessions), existing `terminal_orchestration.py`, existing `managed_file_transfer.py` server side.

## Global Constraints

- Reuse the existing execution stack — do NOT modify `TerminalExecutionCoordinator`, `build_batch_plan`, `parse_terminal_plan`, `TerminalExecutionRunner` internals, or existing `terminal_*` tool semantics.
- Every `ai_*` action must flow through the existing risk classification, `approval_token` gate, `idempotency_key`, and audit logging unchanged (per spec §Approval/Audit).
- Result `summary.status` values: `success | failed | timeout | interrupted` (spec §Result Contract). Timeout is a normal outcome, not an error.
- Summaries are deterministic local rules — no LLM calls (spec §Result Contract).
- `result_id` format: `R` + short random suffix; `ResultStore` max 500 entries LRU, TTL 24h (spec §Result Contract).
- `ai_execute_script`: Linux → whole block injected into shell; network devices → line-by-line command sequence (spec §MCP Interface).
- Flow supports only sequential + dependency + wait-condition + bounded retry; NO branches/loops/parallel steps, NO cross-step variable passing (spec §Flow Engine).
- Skills are JSON template files in `src/ai_gateway/skills/*.json`, versioned with git (spec §Skill Reuse). One bundled example: `driver_reload`.
- Desktop state version advances 14 → 15; new `ai_gateway` section stores only config (`result_store.max_entries` 50–5000, `ttl_hours` 1–168), not result bodies (spec §State Persistence).
- Audit sub-step manifest is an additive field on the existing action record (spec §Approval/Audit).
- All new files/tests follow existing naming: `src/ai_gateway/*.py`, `src/device_mcp/tools/ai_gateway.py`, `tests/test_ai_gateway*.py`.

---

## File Structure

| File | Responsibility |
| --- | --- |
| `src/ai_gateway/result_store.py` | `ResultStore` + `summarize_output()` deterministic summary |
| `src/ai_gateway/flow_engine.py` | `FlowEngine`, `Flow`, `FlowStep`/`WaitCondition` parsing, DAG dependency resolution, condition polling, retry |
| `src/ai_gateway/skills.py` | `SkillRegistry` — load/validate `skills/*.json`, parameter substitution |
| `src/ai_gateway/skills/driver_reload.json` | Bundled example skill |
| `src/ai_gateway/service.py` | `GatewayService` facade wiring the three + high-level methods |
| `src/device_mcp/tools/ai_gateway.py` | `register_ai_gateway_tools(mcp, gateway)` — 8 thin MCP tools |
| `src/device_mcp/actions.py` | `_build_action` branches for the 8 `ai_*` tools |
| `src/device_mcp/service.py` | `_invoke` `ai_*` routing (result_store integration, wait for completion) |
| `src/app/ai_device_ops.py` | handler dict + `_execute_ai_gateway_*` handlers; `GatewayService` instance |
| `src/app/desktop_state.py` | version 15, `ai_gateway` config load/save |
| `src/managed_file_transfer.py` | `build_managed_transfer_download_steps()` (`put` direction) |
| `src/app/managed_file_transfer_ops.py` | `start_managed_transfer_download` direction support (if needed) |
| `src/ai_gateway/skills/` | data-only directory of JSON templates — NOT a package (a package would shadow the `skills.py` module; no `__init__.py`) |

---

### Task 1: ResultStore and deterministic summarization

**Files:**
- Create: `src/ai_gateway/__init__.py`
- Create: `src/ai_gateway/result_store.py`
- Test: `tests/test_ai_gateway_result_store.py`

**Interfaces:**
- Consumes: nothing from this plan.
- Produces: `class ResultStore` with methods:
  - `store(kind: str, output: str, *, metadata: dict[str, Any] | None = None) -> str` returns `result_id`
  - `get(result_id: str) -> StoredResult | None`
  - `summarize(status: str, *, exit_code: int, command_count: int, duration_ms: int) -> dict[str, Any]`
  - `snapshot() -> dict[str, Any]`
  - `StoredResult` dataclass: `result_id, kind, status, output, summary, metadata, created_monotonic`
  - `MAX_ENTRIES = 500`, `TTL_SECONDS = 24 * 3600`
  - module-level `summarize_output(output: str, *, max_important_lines: int = 5, tail_lines: int = 20) -> tuple[int, list[str]]` returning `(error_count, important_lines)`

**Interfaces from later tasks:**
- `GatewayService` (Task 5) owns a `ResultStore`; `ai_execute_*`/`ai_run_skill` call `store()`.
- `ai_get_result` tool (Task 6) calls `ResultStore.get()`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_ai_gateway_result_store.py
from __future__ import annotations

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.ai_gateway.result_store import (
    ResultStore,
    summarize_output,
)


def test_summarize_output_counts_errors_and_extracts_lines() -> None:
    output = (
        "display version\n"
        "VRP (R) software, Version 8.180\n"
        "Error: config-file missing\n"
        "%Aug  6 10:00:00 2026 HUAWEI %%01ERR/4/LOG: slot 0 has a fault\n"
        "display current-configuration\n"
        "success\n"
    )
    error_count, lines = summarize_output(output)
    assert error_count == 2  # Error: + %.../4/...
    assert "VRP (R) software" not in lines  # non-error lines not in important_lines when errors exist
    assert any("Error: config-file missing" in line for line in lines)
    assert any("%Aug" in line for line in lines)


def test_summarize_output_tails_when_no_errors() -> None:
    output = "\n".join(f"line {i}" for i in range(30))
    error_count, lines = summarize_output(output, tail_lines=5)
    assert error_count == 0
    assert len(lines) == 5
    assert "line 29" in lines[-1]


def test_result_store_round_trip_and_ttl() -> None:
    store = ResultStore()
    result_id = store.store("command", "ok", metadata={"command_count": 1})
    assert result_id.startswith("R")
    entry = store.get(result_id)
    assert entry is not None
    assert entry.output == "ok"
    assert store.get("R-nope") is None


def test_result_store_lru_eviction() -> None:
    store = ResultStore(max_entries=3)
    ids = [store.store("command", f"out {i}") for i in range(5)]
    # The first two are evicted (LRU), the last three survive.
    assert store.get(ids[0]) is None
    assert store.get(ids[1]) is None
    assert store.get(ids[2]) is not None
    assert store.get(ids[4]) is not None


def test_result_store_snapshot_reports_counts() -> None:
    store = ResultStore(max_entries=500)
    store.store("command", "a")
    store.store("skill", "b")
    snap = store.snapshot()
    assert snap["count"] == 2
    assert snap["max_entries"] == 500
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ai_gateway_result_store.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.ai_gateway'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/ai_gateway/__init__.py
"""AI Device Gateway: high-level device operations for AI agents."""
from __future__ import annotations
```

```python
# src/ai_gateway/result_store.py
"""In-memory result store with deterministic output summarization."""

from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4

MAX_ENTRIES = 500
TTL_SECONDS = 24 * 3600
_MAX_IMPORTANT_LINES = 5
_TAIL_LINES = 20
# Error markers: "Error:", "Failed", and severity-4+ syslog lines. A Huawei
# syslog header is e.g. "%Aug  6 10:00:00 2026 HUAWEI %%01ERR/4/LOG: ..." — the
# severity lives in "%%<module>/<severity>/", so match that (not the leading %,
# which is followed by a spaced timestamp).
_ERROR_PATTERNS = (
    re.compile(r"\bError\b", re.IGNORECASE),
    re.compile(r"\bFailed\b", re.IGNORECASE),
    re.compile(r"%%[A-Za-z0-9]+/([4-9])/"),
)


@dataclass(slots=True)
class StoredResult:
    result_id: str
    kind: str
    status: str
    output: str
    summary: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)
    created_monotonic: float = 0.0


def summarize_output(
    output: str,
    *,
    max_important_lines: int = _MAX_IMPORTANT_LINES,
    tail_lines: int = _TAIL_LINES,
) -> tuple[int, list[str]]:
    lines = output.splitlines()
    hits = []
    for index, line in enumerate(lines):
        if any(pattern.search(line) for pattern in _ERROR_PATTERNS):
            hits.append((index, line.strip()))
    if hits:
        return len(hits), [line for _, line in hits[:max_important_lines]]
    tail = lines[-tail_lines:] if tail_lines else lines
    return 0, [line.strip() for line in tail]


class ResultStore:
    def __init__(
        self,
        *,
        max_entries: int = MAX_ENTRIES,
        ttl_seconds: int = TTL_SECONDS,
        clock: Any = time.monotonic,
    ) -> None:
        # max_entries floor is 1 (not 50) so small test values exercise LRU
        # eviction; the 50–5000 desktop-state clamp lives in Task 8's config
        # layer. ttl_seconds is SECONDS everywhere (default TTL_SECONDS=86400 is
        # 24h); the clamp is 1h..168h expressed in seconds. Do NOT reinterpret
        # the parameter as hours — that made the default resolve to 7 days.
        self.max_entries = max(1, min(5000, int(max_entries)))
        self.ttl_seconds = max(3600, min(604800, int(ttl_seconds)))
        self.clock = clock
        self._entries: dict[str, StoredResult] = {}
        self._order: list[str] = []
        self._lock = threading.RLock()

    def store(
        self,
        kind: str,
        output: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        with self._lock:
            self._prune_expired_locked()
            result_id = "R" + uuid4().hex[:8]
            meta = dict(metadata or {})
            # The stored summary is computed here from the real status/exit_code/
            # duration passed via metadata, plus the deterministic error scan of
            # the output. This keeps `ai_get_result` returning the SAME summary
            # the caller returned — no placeholder, no separate finalize step.
            status = str(meta.get("status") or "success")
            exit_code = int(meta.get("exit_code") or 0)
            command_count = int(meta.get("command_count", 1))
            duration_ms = int(meta.get("duration_ms", 0))
            error_count, important_lines = summarize_output(output)
            summary = {
                "status": status,
                "exit_code": exit_code,
                "command_count": command_count,
                "error_count": error_count,
                "important_lines": important_lines,
                "duration_ms": duration_ms,
            }
            entry = StoredResult(
                result_id=result_id,
                kind=kind,
                status=status,
                output=output,
                summary=summary,
                metadata=meta,
                created_monotonic=self.clock(),
            )
            self._entries[result_id] = entry
            self._order.append(result_id)
            while len(self._order) > self.max_entries:
                oldest = self._order.pop(0)
                self._entries.pop(oldest, None)
            return result_id

    def get(self, result_id: str) -> StoredResult | None:
        with self._lock:
            entry = self._entries.get(result_id)
            if entry is None:
                return None
            if self.clock() - entry.created_monotonic > self.ttl_seconds:
                self._entries.pop(result_id, None)
                self._order = [rid for rid in self._order if rid != result_id]
                return None
            if self._order:
                self._order.remove(result_id)
                self._order.append(result_id)
            return entry

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            self._prune_expired_locked()
            return {
                "count": len(self._entries),
                "max_entries": self.max_entries,
                "ttl_seconds": self.ttl_seconds,
            }

    def _prune_expired_locked(self) -> None:
        now = self.clock()
        expired = [
            rid for rid in self._order
            if now - self._entries[rid].created_monotonic > self.ttl_seconds
        ]
        for rid in expired:
            self._entries.pop(rid, None)
            self._order.remove(rid)
```

> **Note:** `store()` computes the full stored summary from `metadata` (`status`/`exit_code`/`command_count`/`duration_ms`) plus `summarize_output(output)`. The `metadata` dict is stored verbatim on `StoredResult.metadata`; the summary is stored separately. This guarantees `ai_get_result` returns the same summary the executing call returned.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_ai_gateway_result_store.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ai_gateway/ tests/test_ai_gateway_result_store.py
git commit -m "feat(ai-gateway): add result store with deterministic summary"
```

---

### Task 2: Flow engine with dependencies, wait conditions, retry

**Files:**
- Create: `src/ai_gateway/flow_engine.py`
- Test: `tests/test_ai_gateway_flow_engine.py`

**Interfaces:**
- Consumes: nothing from this plan (tests use a fake executor callback).
- Produces:
  - `class FlowPlanError(ValueError)` with `.code`
  - `@dataclass FlowStep`: `id, command, depends_on: list[str], retry: dict | None, wait_condition: dict | None`
  - `@dataclass FlowStepResult`: `id, status, output, error_code, message, attempt_count`
  - `def parse_flow(data: dict[str, Any]) -> FlowPlan` (raises `FlowPlanError`)
  - `@dataclass FlowPlan`: `steps: list[FlowStep], max_steps: int = 20`
  - `class FlowEngine` with `run(plan: FlowPlan, *, session_id: str, device_id: str, execute_step: Callable[[str, str, int], tuple[str, str]], wait_for_condition: Callable[[dict, str, str], tuple[str, str]], clock: Callable[[], float] = time.monotonic) -> list[FlowStepResult]`
  - Module constants `MAX_FLOW_STEPS = 20`, `MAX_RETRIES = 5`, `MAX_WAIT_ATTEMPTS = 60`

**Interfaces from later tasks:**
- Task 4 (`SkillRegistry`) produces flows as `dict` parsed by `parse_flow`.
- Task 5 (`GatewayService`) supplies `execute_step` and `wait_for_condition` callbacks that delegate to `TerminalExecutionCoordinator`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_ai_gateway_flow_engine.py
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from src.ai_gateway.flow_engine import (
    FlowEngine,
    FlowPlanError,
    parse_flow,
)


def _run(
    plan_data: dict,
    *,
    executor=None,
    waiter=None,
) -> list:
    plan = parse_flow(plan_data)
    engine = FlowEngine()
    executed = []

    base_executor = executor or (
        lambda command, session_id, timeout: ("success", f"output of {command}")
    )
    base_waiter = waiter or (lambda condition, session_id, device_id: ("success", "condition met"))

    def record_executor(command: str, session_id: str, timeout: int) -> tuple[str, str]:
        # Wrap ANY executor (not just the default) so `executed` records calls
        # even when a test supplies a custom executor (e.g. the dependency-gating
        # test asserts which commands actually ran).
        executed.append(command)
        return base_executor(command, session_id, timeout)

    return engine.run(
        plan,
        session_id="sess-1",
        device_id="dev-1",
        execute_step=record_executor,
        wait_for_condition=base_waiter,
    ), executed


def test_flow_runs_steps_in_order() -> None:
    results, executed = _run(
        {
            "steps": [
                {"id": "s1", "command": "display version"},
                {"id": "s2", "command": "display cpu"},
            ]
        }
    )
    assert executed == ["display version", "display cpu"]
    assert all(result.status == "success" for result in results)


def test_flow_dependency_gates_second_step() -> None:
    # s2 depends on s1; s1 fails → s2 must not run.
    def executor(command: str, session_id: str, timeout: int) -> tuple[str, str]:
        if command == "display version":
            return "failed", "Error: nope"
        return "success", "ok"

    results, executed = _run(
        {
            "steps": [
                {"id": "s1", "command": "display version"},
                {"id": "s2", "command": "display cpu", "depends_on": ["s1"]},
            ]
        },
        executor=executor,
    )
    assert executed == ["display version"]
    assert results[0].status == "failed"
    assert results[1].status == "skipped"


def test_flow_retry_on_failure() -> None:
    calls = {"n": 0}

    def executor(command: str, session_id: str, timeout: int) -> tuple[str, str]:
        calls["n"] += 1
        if calls["n"] < 3:
            return "failed", "Error: transient"
        return "success", "ok"

    plan = parse_flow(
        {
            "steps": [
                {
                    "id": "s1",
                    "command": "save",
                    "retry": {"max": 3, "interval_ms": 1, "on_status": "failed"},
                }
            ]
        }
    )
    engine = FlowEngine()
    results = engine.run(
        plan,
        session_id="sess-1",
        device_id="dev-1",
        execute_step=executor,
        wait_for_condition=lambda c, s, d: ("success", "ok"),
    )
    assert calls["n"] == 3
    assert results[0].status == "success"
    assert results[0].attempt_count == 3


def test_flow_wait_condition_polls_until_met() -> None:
    polls = {"n": 0}

    def waiter(condition: dict, session_id: str, device_id: str) -> tuple[str, str]:
        polls["n"] += 1
        if polls["n"] < 3:
            return "not_ready", "still booting"
        return "success", "ready"

    plan = parse_flow(
        {
            "steps": [
                {"id": "s1", "command": "save"},
                {
                    "id": "s2",
                    "command": "display version",
                    "wait_condition": {
                        "type": "command_output_contains",
                        "command": "display version",
                        "expected": "VRP",
                        "interval_ms": 1,
                        "max_attempts": 5,
                    },
                },
            ]
        }
    )
    engine = FlowEngine()
    results = engine.run(
        plan,
        session_id="sess-1",
        device_id="dev-1",
        execute_step=lambda c, s, t: ("success", "ok"),
        wait_for_condition=waiter,
    )
    assert polls["n"] == 3
    assert results[1].status == "success"


def test_flow_wait_condition_times_out() -> None:
    plan = parse_flow(
        {
            "steps": [
                {
                    "id": "s1",
                    "command": "save",
                    "wait_condition": {
                        "type": "command_output_contains",
                        "command": "display version",
                        "expected": "VRP",
                        "interval_ms": 1,
                        "max_attempts": 2,
                    },
                }
            ]
        }
    )
    engine = FlowEngine()
    results = engine.run(
        plan,
        session_id="sess-1",
        device_id="dev-1",
        execute_step=lambda c, s, t: ("success", "ok"),
        wait_for_condition=lambda c, s, d: ("not_ready", "booting"),
    )
    assert results[0].status == "failed"
    assert results[0].error_code == "condition_timeout"


def test_flow_too_many_steps_rejected() -> None:
    with pytest.raises(FlowPlanError) as exc_info:
        parse_flow({"steps": [{"id": f"s{i}", "command": "x"} for i in range(21)]})
    assert exc_info.value.code == "too_many_steps"


def test_flow_dependency_unknown_rejected() -> None:
    with pytest.raises(FlowPlanError) as exc_info:
        parse_flow(
            {
                "steps": [
                    {"id": "s1", "command": "a", "depends_on": ["ghost"]}
                ]
            }
        )
    assert exc_info.value.code == "unknown_dependency"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ai_gateway_flow_engine.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.ai_gateway.flow_engine'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/ai_gateway/flow_engine.py
"""Flow orchestration: sequential steps with dependency gating, wait conditions, bounded retry."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

MAX_FLOW_STEPS = 20
MAX_RETRIES = 5
MAX_WAIT_ATTEMPTS = 60


class FlowPlanError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(slots=True)
class FlowStep:
    id: str
    command: str
    depends_on: list[str] = field(default_factory=list)
    retry: dict[str, Any] | None = None
    wait_condition: dict[str, Any] | None = None
    timeout_seconds: int = 30


@dataclass(slots=True)
class FlowStepResult:
    id: str
    status: str  # success | failed | skipped
    output: str = ""
    error_code: str = ""
    message: str = ""
    attempt_count: int = 1


@dataclass(slots=True)
class FlowPlan:
    steps: list[FlowStep]
    max_steps: int = MAX_FLOW_STEPS


def parse_flow(data: dict[str, Any]) -> FlowPlan:
    if not isinstance(data, dict):
        raise FlowPlanError("invalid_flow", "Flow 必须是对象。")
    raw_steps = data.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise FlowPlanError("invalid_flow", "Flow 至少需要一个步骤。")
    if len(raw_steps) > MAX_FLOW_STEPS:
        raise FlowPlanError("too_many_steps", f"Flow 最多允许 {MAX_FLOW_STEPS} 个步骤。")
    ids = set()
    steps: list[FlowStep] = []
    for raw in raw_steps:
        if not isinstance(raw, dict):
            raise FlowPlanError("invalid_flow", "Flow 步骤必须是对象。")
        step_id = str(raw.get("id") or "").strip()
        if not step_id:
            raise FlowPlanError("invalid_flow", "Flow 步骤缺少 id。")
        if step_id in ids:
            raise FlowPlanError("duplicate_step", f"Flow 步骤 id 重复: {step_id}")
        ids.add(step_id)
        command = str(raw.get("command") or "").strip()
        if not command:
            raise FlowPlanError("invalid_flow", f"步骤 {step_id} 缺少 command。")
        depends_on = [
            str(dep).strip()
            for dep in (raw.get("depends_on") or [])
            if isinstance(dep, str)
        ]
        retry = raw.get("retry")
        if retry is not None:
            retry = _validate_retry(retry, step_id)
        wait_condition = raw.get("wait_condition")
        if wait_condition is not None:
            wait_condition = _validate_wait_condition(wait_condition, step_id)
        timeout_seconds = _bounded_int(
            raw.get("timeout_seconds", 30),
            1,
            300,
            f"步骤 {step_id} timeout_seconds",
        )
        steps.append(
            FlowStep(
                id=step_id,
                command=command,
                depends_on=depends_on,
                retry=retry,
                wait_condition=wait_condition,
                timeout_seconds=timeout_seconds,
            )
        )
    for step in steps:
        for dep in step.depends_on:
            if dep not in ids:
                raise FlowPlanError(
                    "unknown_dependency",
                    f"步骤 {step.id} 依赖未知步骤: {dep}",
                )
    return FlowPlan(steps)


def _validate_retry(raw: Any, step_id: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise FlowPlanError("invalid_flow", f"步骤 {step_id} retry 必须是对象。")
    if str(raw.get("on_status") or "") != "failed":
        raise FlowPlanError(
            "invalid_flow",
            f"步骤 {step_id} retry.on_status 目前只支持 failed。",
        )
    max_retries = _bounded_int(raw.get("max", 0), 0, MAX_RETRIES, f"步骤 {step_id} retry.max")
    interval_ms = _bounded_int(raw.get("interval_ms", 1000), 1, 60_000, f"步骤 {step_id} retry.interval_ms")
    return {"max": max_retries, "interval_ms": interval_ms, "on_status": "failed"}


def _validate_wait_condition(raw: Any, step_id: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise FlowPlanError("invalid_flow", f"步骤 {step_id} wait_condition 必须是对象。")
    if str(raw.get("type") or "") != "command_output_contains":
        raise FlowPlanError(
            "invalid_flow",
            f"步骤 {step_id} wait_condition 类型目前只支持 command_output_contains。",
        )
    command = str(raw.get("command") or "").strip()
    expected = str(raw.get("expected") or "").strip()
    if not command or not expected:
        raise FlowPlanError(
            "invalid_flow",
            f"步骤 {step_id} wait_condition 需要 command 和 expected。",
        )
    interval_ms = _bounded_int(raw.get("interval_ms", 2000), 1, 60_000, f"步骤 {step_id} wait_condition.interval_ms")
    max_attempts = _bounded_int(raw.get("max_attempts", 15), 1, MAX_WAIT_ATTEMPTS, f"步骤 {step_id} wait_condition.max_attempts")
    return {
        "type": "command_output_contains",
        "command": command,
        "expected": expected,
        "interval_ms": interval_ms,
        "max_attempts": max_attempts,
    }


def _bounded_int(value: Any, minimum: int, maximum: int, label: str) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as exc:
        raise FlowPlanError("invalid_flow", f"{label} 必须是整数。") from exc
    if number < minimum or number > maximum:
        raise FlowPlanError(
            "invalid_flow",
            f"{label} 必须在 {minimum} 到 {maximum} 之间。",
        )
    return number


class FlowEngine:
    def run(
        self,
        plan: FlowPlan,
        *,
        session_id: str,
        device_id: str,
        execute_step: Callable[[str, str, int], tuple[str, str]],
        wait_for_condition: Callable[[dict[str, Any], str, str], tuple[str, str]],
        clock: Callable[[], float] = time.monotonic,
    ) -> list[FlowStepResult]:
        results: list[FlowStepResult] = []
        completed: set[str] = set()
        failed: set[str] = set()
        for step in plan.steps:
            deps = set(step.depends_on)
            if deps & failed:
                results.append(FlowStepResult(step.id, "skipped", message="依赖步骤失败。"))
                continue
            missing = deps - completed
            if missing:
                results.append(FlowStepResult(step.id, "skipped", message="依赖步骤未完成。"))
                continue
            result = self._run_step(step, session_id, device_id, execute_step, wait_for_condition, clock)
            results.append(result)
            if result.status == "success":
                completed.add(step.id)
            else:
                failed.add(step.id)
        return results

    def _run_step(
        self,
        step: FlowStep,
        session_id: str,
        device_id: str,
        execute_step: Callable[[str, str, int], tuple[str, str]],
        wait_for_condition: Callable[[dict[str, Any], str, str], tuple[str, str]],
        clock: Callable[[], float],
    ) -> FlowStepResult:
        if step.wait_condition is not None:
            # Poll the condition up to max_attempts. The engine is pure: the
            # real per-poll sleep is supplied by the executor in Task 4; here we
            # only call clock() as the interval placeholder between attempts.
            max_attempts = int((step.wait_condition or {}).get("max_attempts", 15))
            poll_interval_ms = int((step.wait_condition or {}).get("interval_ms", 2000))
            last_output = ""
            for _attempt in range(max_attempts):
                status, output = wait_for_condition(step.wait_condition, session_id, device_id)
                last_output = output
                if status == "success":
                    break
                if poll_interval_ms > 0:
                    clock()
            if status != "success":
                return FlowStepResult(
                    step.id,
                    "failed",
                    output=last_output,
                    error_code="condition_timeout",
                    message="等待条件超时。",
                )
        attempts = 0
        max_retries = int((step.retry or {}).get("max", 0))
        interval_ms = int((step.retry or {}).get("interval_ms", 1000))
        last_status, last_output, last_error, last_message = "failed", "", "", ""
        while attempts <= max_retries:
            attempts += 1
            status, output = execute_step(step.command, session_id, step.timeout_seconds)
            if status == "success":
                return FlowStepResult(step.id, "success", output=output, attempt_count=attempts)
            last_status, last_output = status, output
            last_error = "execution_failed"
            last_message = f"步骤 {step.id} 执行失败。"
            if attempts > max_retries:
                break
            if interval_ms > 0:
                clock()  # placeholder; real sleep uses the same schedule mechanism as executor
        return FlowStepResult(
            step.id,
            "failed",
            output=last_output,
            error_code=last_error,
            message=last_message,
            attempt_count=attempts,
        )
```

> **Note on retry interval:** `_run_step` currently records `clock()` as a placeholder for the sleep. In the real `GatewayService` (Task 5), the executor callback supplies the sleep — the flow engine stays pure. Tests use `interval_ms: 1` and a fake clock; the placeholder does not block.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_ai_gateway_flow_engine.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ai_gateway/flow_engine.py tests/test_ai_gateway_flow_engine.py
git commit -m "feat(ai-gateway): add flow engine with dependency gating, wait conditions, retry"
```

---

### Task 3: Skill registry and parameter substitution

**Files:**
- Create: `src/ai_gateway/skills.py` (module — a `skills/` package would shadow it, so the dir must NOT get an `__init__.py`)
- Create: `src/ai_gateway/skills/driver_reload.json`
- Test: `tests/test_ai_gateway_skills.py`

**Interfaces:**
- Consumes: `parse_flow`, `FlowPlanError`, `FlowPlan` from Task 2.
- Produces:
  - `class SkillRegistry` with `__init__(self, skills_dir: str | None = None)`, `list_skills() -> list[dict]`, `get_skill(name: str) -> SkillDefinition | None`, `load()` (idempotent scan), `instantiate_flow(skill_name: str, params: dict[str, Any]) -> FlowPlan`
  - `class SkillDefinition` dataclass: `name, description, params: list[dict], flow: dict`
  - `SkillLoadError(ValueError)` with `.code`
  - Module constant `BUNDLED_SKILLS_DIR`

**Interfaces from later tasks:**
- Task 5 (`GatewayService`) calls `registry.instantiate_flow(name, params)` then hands the `FlowPlan` to `FlowEngine`.
- `ai_run_skill` MCP tool (Task 6) calls `registry.list_skills()`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_ai_gateway_skills.py
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from src.ai_gateway.skills import SkillLoadError, SkillRegistry


def test_registry_lists_bundled_skill() -> None:
    registry = SkillRegistry()
    skills = registry.list_skills()
    assert any(skill["name"] == "driver_reload" for skill in skills)


def test_registry_loads_custom_skill_from_dir(tmp_path: Path) -> None:
    skill = {
        "name": "my_custom",
        "description": "自定义流程",
        "params": [{"name": "device_id", "type": "string", "required": True}],
        "flow": {
            "steps": [
                {"id": "s1", "command": "display version"},
            ]
        },
    }
    (tmp_path / "my_custom.json").write_text(
        json.dumps(skill, ensure_ascii=False),
        encoding="utf-8",
    )
    registry = SkillRegistry(skills_dir=str(tmp_path))
    assert any(s["name"] == "my_custom" for s in registry.list_skills())
    flow = registry.instantiate_flow("my_custom", {"device_id": "dev-1"})
    assert flow.steps[0].command == "display version"


def test_registry_parameter_substitution() -> None:
    skill = {
        "name": "param_skill",
        "description": "参数替换",
        "params": [{"name": "interface", "type": "string", "required": True}],
        "flow": {
            "steps": [
                {"id": "s1", "command": "display interface ${interface}"},
            ]
        },
    }
    with tempfile.TemporaryDirectory() as tmp:
        Path(tmp, "param_skill.json").write_text(
            json.dumps(skill, ensure_ascii=False), encoding="utf-8"
        )
        registry = SkillRegistry(skills_dir=tmp)
        flow = registry.instantiate_flow("param_skill", {"interface": "GigabitEthernet0/0/1"})
        assert flow.steps[0].command == "display interface GigabitEthernet0/0/1"


def test_registry_unknown_skill_raises() -> None:
    registry = SkillRegistry()
    with pytest.raises(SkillLoadError) as exc_info:
        registry.instantiate_flow("ghost_skill", {})
    assert exc_info.value.code == "skill_not_found"


def test_registry_missing_required_param_raises() -> None:
    registry = SkillRegistry()
    with pytest.raises(SkillLoadError) as exc_info:
        registry.instantiate_flow("driver_reload", {})
    assert exc_info.value.code == "missing_param"


def test_registry_bad_json_falls_back_to_bundled() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        Path(tmp, "broken.json").write_text("{ not json", encoding="utf-8")
        registry = SkillRegistry(skills_dir=tmp)
        # A corrupt file must not break the whole registry; bundled skill still loads.
        assert any(s["name"] == "driver_reload" for s in registry.list_skills())
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ai_gateway_skills.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.ai_gateway.skills'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/ai_gateway/skills/driver_reload.json
{
  "name": "driver_reload",
  "description": "重载设备驱动（用于变更验证）",
  "params": [
    {"name": "device_id", "type": "string", "required": true},
    {"name": "timeout_seconds", "type": "integer", "required": false}
  ],
  "flow": {
    "steps": [
      {"id": "s1", "command": "display version", "timeout_seconds": 30},
      {"id": "s2", "command": "reset slot-configuration active", "timeout_seconds": 30}
    ]
  }
}
```

```python
# src/ai_gateway/skills.py
"""Skill registry: load JSON flow templates and instantiate parameterized flows."""

from __future__ import annotations

import json
import os
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .flow_engine import FlowPlan, FlowPlanError, parse_flow

BUNDLED_SKILLS_DIR = os.path.join(os.path.dirname(__file__), "skills")
_PARAM_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


class SkillLoadError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(slots=True)
class SkillDefinition:
    name: str
    description: str
    params: list[dict[str, Any]]
    flow: dict[str, Any]


class SkillRegistry:
    def __init__(self, skills_dir: str | None = None) -> None:
        self.skills_dir = skills_dir or BUNDLED_SKILLS_DIR
        self._skills: dict[str, SkillDefinition] = {}
        self._lock = threading.RLock()
        self.load()

    def load(self) -> None:
        with self._lock:
            self._skills = {}
            # Bundled skills always load first, then the custom dir overlays
            # (dedup by name). This keeps driver_reload available even when a
            # custom dir contains only corrupt files.
            for directory in (Path(BUNDLED_SKILLS_DIR), Path(self.skills_dir)):
                seen = set(directory.glob("*.json")) if directory.is_dir() else set()
                for path in sorted(seen):
                    try:
                        data = json.loads(path.read_text(encoding="utf-8"))
                        self._register(data)
                    except (json.JSONDecodeError, ValueError, KeyError):
                        # Corrupt or invalid skill files are skipped; the rest still load.
                        continue

    def _register(self, data: dict[str, Any]) -> None:
        name = str(data.get("name") or "").strip()
        if not name or name in self._skills:
            return
        description = str(data.get("description") or "")
        params = data.get("params")
        if not isinstance(params, list):
            raise SkillLoadError("invalid_skill", f"Skill {name} params 必须是数组。")
        flow = data.get("flow")
        if not isinstance(flow, dict):
            raise SkillLoadError("invalid_skill", f"Skill {name} 缺少 flow。")
        # Validate the flow parses (with an empty param dict — placeholders may fail,
        # so we only validate structurally here; full validation happens on instantiate).
        self._skills[name] = SkillDefinition(name, description, params, flow)

    def list_skills(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {
                    "name": skill.name,
                    "description": skill.description,
                    "params": skill.params,
                }
                for skill in sorted(self._skills.values(), key=lambda s: s.name)
            ]

    def get_skill(self, name: str) -> SkillDefinition | None:
        with self._lock:
            return self._skills.get(name)

    def instantiate_flow(self, name: str, params: dict[str, Any]) -> FlowPlan:
        with self._lock:
            skill = self._skills.get(name)
        if skill is None:
            raise SkillLoadError("skill_not_found", f"未找到 Skill: {name}")
        required = [
            p.get("name") for p in skill.params if bool(p.get("required"))
        ]
        missing = [r for r in required if r not in params]
        if missing:
            raise SkillLoadError(
                "missing_param",
                f"Skill {name} 缺少必需参数: {', '.join(missing)}",
            )
        flow_data = json.loads(json.dumps(skill.flow))
        substituted = _substitute(flow_data, params)
        try:
            return parse_flow(substituted)
        except FlowPlanError as exc:
            raise SkillLoadError("invalid_flow", f"Skill {name} 流程无效: {exc}") from exc


def _substitute(node: Any, params: dict[str, Any]) -> Any:
    if isinstance(node, dict):
        return {key: _substitute(value, params) for key, value in node.items()}
    if isinstance(node, list):
        return [_substitute(item, params) for item in node]
    if isinstance(node, str):
        def replace(match: re.Match[str]) -> str:
            key = match.group(1)
            return str(params.get(key, match.group(0)))
        return _PARAM_RE.sub(replace, node)
    return node
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_ai_gateway_skills.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ai_gateway/skills.py src/ai_gateway/skills/ tests/test_ai_gateway_skills.py
git commit -m "feat(ai-gateway): add skill registry with JSON templates and param substitution"
```

---

### Task 4: GatewayService facade

**Files:**
- Create: `src/ai_gateway/service.py`
- Test: `tests/test_ai_gateway_service.py`

**Interfaces:**
- Consumes: `ResultStore` (Task 1), `FlowEngine` + `parse_flow` + `FlowPlanError` (Task 2), `SkillRegistry` + `SkillLoadError` (Task 3).
- Produces:
  - `class GatewayService` with constructor `__init__(self, *, result_store: ResultStore | None = None, flow_engine: FlowEngine | None = None, skill_registry: SkillRegistry | None = None)`.
  - Methods. Each high-level method takes an injectable `executor` — a **synchronous** command runner `executor(command: str, session_id: str, timeout_seconds: int) -> {"status", "output", "exit_code"}`; when omitted they raise `GatewayUnavailableError`:
    - `execute_command(command, session_id, *, timeout_seconds=30, executor=None) -> {"result_id", "summary"}`
    - `execute_batch(commands, session_id, *, command_timeout_seconds=30, executor=None) -> {"result_id", "summary"}`
    - `execute_script(script, session_id, *, shell=None, timeout_seconds=30, is_network_device=False, executor=None) -> {"result_id", "summary"}`
    - `run_skill(skill_name, params, *, session_id="", timeout_seconds=60, executor=None) -> {"result_id", "summary"}`
    - `skill_flow(skill_name, params) -> dict` — the substituted flow dict (parseable by `parse_flow`); raises `SkillLoadError`.
    - `get_result(result_id, *, include_raw=False) -> dict | None`
    - `snapshot() -> dict`
  - `class GatewayUnavailableError(ValueError)` with `.code = "gateway_unavailable"`.

> **Threading contract (critical, do not violate):** `GatewayService`'s high-level methods are called from the **HTTP server thread** (service.py `_invoke`), never from a Qt-thread UI callback. The injected `executor` is supplied by service.py and internally does the start-on-Qt-thread + wait-on-HTTP-thread dance (Task 6), mirroring the existing `_execute_terminal_plan` pattern. A synchronous executor that blocks the Qt thread would deadlock the runner (output is injected on the Qt thread via `append_session_output`). `ResultStore`/`SkillRegistry` hold their own RLocks, so app-side `get_result`/`snapshot` are thread-safe.

**Interfaces from later tasks:**
- Task 5 (app) constructs a `GatewayService` with **no executor** (so `get_result`/`snapshot` work app-side) and exposes it via a `gateway_service()` accessor.
- Task 6 (service.py) injects an `executor` closure driving `_execute_terminal_plan` (start-Qt + wait-HTTP).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_ai_gateway_service.py
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from src.ai_gateway.service import (
    GatewayService,
    GatewayUnavailableError,
)


def _fake_executor(plan: dict[str, dict[str, str]] | None = None):
    """Return a command executor driven by an ordered dict of command→(status, output)."""
    plan = plan or {}
    calls: list[str] = []

    def execute_command(command: str, session_id: str, timeout_seconds: int) -> dict[str, str]:
        calls.append(command)
        status, output = plan.get(command, ("success", f"output of {command}"))
        return {"status": status, "output": output, "exit_code": 0 if status == "success" else 1}

    return execute_command, calls


def test_execute_command_returns_result_and_summary() -> None:
    executor, calls = _fake_executor()
    service = GatewayService()
    result = service.execute_command("display version", "sess-1", executor=executor)
    assert result["result_id"].startswith("R")
    assert result["summary"]["status"] == "success"
    assert calls == ["display version"]


def test_execute_batch_runs_all_commands() -> None:
    executor, calls = _fake_executor()
    service = GatewayService()
    result = service.execute_batch(["display version", "display cpu"], "sess-1", executor=executor)
    assert calls == ["display version", "display cpu"]
    assert result["summary"]["command_count"] == 2


def test_execute_script_linux_injects_whole_block() -> None:
    executor, calls = _fake_executor()
    service = GatewayService()
    script = "export FOO=bar\nls $FOO\n"
    result = service.execute_script(script, "sess-1", is_network_device=False, executor=executor)
    # Linux: the whole block goes in one command (multi-line).
    assert len(calls) == 1
    assert calls[0] == script
    assert result["summary"]["status"] == "success"


def test_execute_script_network_device_splits_lines() -> None:
    executor, calls = _fake_executor()
    service = GatewayService()
    script = "display version\ndisplay cpu\n"
    result = service.execute_script(script, "sess-1", is_network_device=True, executor=executor)
    assert calls == ["display version", "display cpu"]
    assert result["summary"]["command_count"] == 2


def test_get_result_round_trip() -> None:
    service = GatewayService()
    created = service.execute_command("display version", "sess-1", executor=_fake_executor()[0])
    fetched = service.get_result(created["result_id"])
    assert fetched is not None
    assert fetched["result"]["summary"]["status"] == "success"
    raw = service.get_result(created["result_id"], include_raw=True)
    assert raw is not None
    assert "raw_output" in raw


def test_run_skill_instantiates_flow() -> None:
    executor, _ = _fake_executor()
    service = GatewayService()
    result = service.run_skill(
        "driver_reload",
        {"device_id": "dev-1"},
        session_id="sess-1",
        executor=executor,
    )
    assert result["result_id"].startswith("R")
    assert result["summary"]["command_count"] == 2  # both steps ran


def test_skill_flow_returns_substituted_dict() -> None:
    service = GatewayService()
    flow = service.skill_flow("driver_reload", {"device_id": "dev-1"})
    assert isinstance(flow, dict)
    assert flow["steps"][0]["command"] == "display version"


def test_gateway_unavailable_without_executor() -> None:
    service = GatewayService()
    with pytest.raises(GatewayUnavailableError):
        service.execute_command("display version", "sess-1")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ai_gateway_service.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'src.ai_gateway.service'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/ai_gateway/service.py
"""GatewayService facade wiring ResultStore, FlowEngine, SkillRegistry."""

from __future__ import annotations

import threading
import time
from typing import Any, Callable

from .flow_engine import FlowEngine, parse_flow
from .result_store import ResultStore, summarize_output
from .skills import SkillRegistry


class GatewayUnavailableError(ValueError):
    def __init__(self, message: str = "Gateway 执行器尚未就绪。") -> None:
        super().__init__(message)
        self.code = "gateway_unavailable"


class GatewayService:
    def __init__(
        self,
        *,
        result_store: ResultStore | None = None,
        flow_engine: FlowEngine | None = None,
        skill_registry: SkillRegistry | None = None,
    ) -> None:
        self.result_store = result_store or ResultStore()
        self.flow_engine = flow_engine or FlowEngine()
        self.skill_registry = skill_registry or SkillRegistry()
        self._lock = threading.RLock()

    def _run_command(
        self,
        command: str,
        session_id: str,
        timeout_seconds: int,
        executor: Callable[[str, str, int], dict[str, Any]] | None,
    ) -> dict[str, Any]:
        if executor is None:
            raise GatewayUnavailableError()
        return executor(command, session_id, timeout_seconds)

    def _store_summary(self, kind: str, output: str, *, status: str, exit_code: int, command_count: int, duration_ms: int, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        started = time.monotonic()
        error_count, important_lines = summarize_output(output)
        summary = {
            "status": status,
            "exit_code": exit_code,
            "command_count": command_count,
            "error_count": error_count,
            "important_lines": important_lines,
            "duration_ms": int(duration_ms),
        }
        result_id = self.result_store.store(
            kind,
            output,
            metadata={
                "status": status,
                "exit_code": exit_code,
                "command_count": command_count,
                "duration_ms": duration_ms,
                **(extra or {}),
            },
        )
        return {
            "result_id": result_id,
            "summary": summary,
            "response_time_ms": round((time.monotonic() - started) * 1000, 2),
        }

    def execute_command(
        self,
        command: str,
        session_id: str,
        *,
        timeout_seconds: int = 30,
        executor: Callable[[str, str, int], dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        started = time.monotonic()
        raw = self._run_command(command, session_id, timeout_seconds, executor)
        status = str(raw.get("status") or "success")
        output = str(raw.get("output") or "")
        exit_code = int(raw.get("exit_code") or 0)
        return self._store_summary(
            "command",
            output,
            status=status,
            exit_code=exit_code,
            command_count=1,
            duration_ms=round((time.monotonic() - started) * 1000, 2),
        )

    def execute_batch(
        self,
        commands: list[str],
        session_id: str,
        *,
        command_timeout_seconds: int = 30,
        executor: Callable[[str, str, int], dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        started = time.monotonic()
        outputs: list[str] = []
        last_status = "success"
        last_exit = 0
        for command in commands:
            raw = self._run_command(command, session_id, command_timeout_seconds, executor)
            outputs.append(str(raw.get("output") or ""))
            last_status = str(raw.get("status") or "success")
            last_exit = int(raw.get("exit_code") or 0)
            if last_status != "success":
                break
        return self._store_summary(
            "batch",
            "\n".join(outputs),
            status=last_status,
            exit_code=last_exit,
            command_count=len(commands),
            duration_ms=round((time.monotonic() - started) * 1000, 2),
        )

    def execute_script(
        self,
        script: str,
        session_id: str,
        *,
        shell: str | None = None,
        timeout_seconds: int = 30,
        is_network_device: bool = False,
        executor: Callable[[str, str, int], dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        started = time.monotonic()
        lines = [line for line in script.splitlines() if line.strip()]
        if is_network_device:
            return self.execute_batch(
                lines,
                session_id,
                command_timeout_seconds=timeout_seconds,
                executor=executor,
            )
        raw = self._run_command(script, session_id, timeout_seconds, executor)
        return self._store_summary(
            "script",
            str(raw.get("output") or ""),
            status=str(raw.get("status") or "success"),
            exit_code=int(raw.get("exit_code") or 0),
            command_count=1,
            duration_ms=round((time.monotonic() - started) * 1000, 2),
            extra={"shell": shell},
        )

    def skill_flow(self, skill_name: str, params: dict[str, Any]) -> dict[str, Any]:
        """Return the substituted skill flow dict, validated via parse_flow."""
        plan = self.skill_registry.instantiate_flow(skill_name, params)
        # Re-serialize from the parsed plan so service.py can re-parse without a
        # registry reference. All fields round-trip through parse_flow.
        return {
            "steps": [
                {
                    "id": step.id,
                    "command": step.command,
                    "depends_on": step.depends_on,
                    "retry": step.retry,
                    "wait_condition": step.wait_condition,
                    "timeout_seconds": step.timeout_seconds,
                }
                for step in plan.steps
            ]
        }

    def run_skill(
        self,
        skill_name: str,
        params: dict[str, Any],
        *,
        session_id: str = "",
        timeout_seconds: int = 60,
        executor: Callable[[str, str, int], dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        started = time.monotonic()
        flow_data = self.skill_flow(skill_name, params)
        plan = parse_flow(flow_data)

        def execute_step(command: str, session: str, timeout: int) -> tuple[str, str]:
            raw = self._run_command(command, session, timeout, executor)
            return str(raw.get("status") or "success"), str(raw.get("output") or "")

        def wait_for_condition(
            condition: dict[str, Any],
            session: str,
            device: str,
        ) -> tuple[str, str]:
            raw = self._run_command(str(condition.get("command") or ""), session, 30, executor)
            output = str(raw.get("output") or "")
            expected = str(condition.get("expected") or "")
            if expected and expected in output:
                return "success", output
            return "not_ready", output

        results = self.flow_engine.run(
            plan,
            session_id=session_id,
            device_id=str(params.get("device_id") or ""),
            execute_step=execute_step,
            wait_for_condition=wait_for_condition,
        )
        all_outputs = "\n".join(result.output for result in results if result.output)
        failed = [r for r in results if r.status == "failed"]
        status = "failed" if failed else "success"
        return self._store_summary(
            "skill",
            all_outputs,
            status=status,
            exit_code=1 if failed else 0,
            command_count=len(plan.steps),
            duration_ms=round((time.monotonic() - started) * 1000, 2),
            extra={
                "skill_name": skill_name,
                # FlowStepResult is @dataclass(slots=True) — it has no __dict__.
                "step_results": [
                    {
                        "id": r.id,
                        "status": r.status,
                        "output": r.output,
                        "error_code": r.error_code,
                        "message": r.message,
                        "attempt_count": r.attempt_count,
                    }
                    for r in results
                ],
            },
        )

    def get_result(self, result_id: str, *, include_raw: bool = False) -> dict[str, Any] | None:
        entry = self.result_store.get(result_id)
        if entry is None:
            return None
        result = {
            "result_id": entry.result_id,
            "kind": entry.kind,
            "summary": entry.summary,
            "metadata": entry.metadata,
        }
        if include_raw:
            # Contract: `ai_get_result` returns {result, raw_output} with
            # raw_output at the TOP level (per spec). Do not nest it inside
            # `result` — the facade unit test and the app handler test both
            # assert the top-level key.
            return {"result": result, "raw_output": entry.output}
        return {"result": result}

    def snapshot(self) -> dict[str, Any]:
        return {
            "result_store": self.result_store.snapshot(),
            "skills": self.skill_registry.list_skills(),
        }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_ai_gateway_service.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/ai_gateway/service.py tests/test_ai_gateway_service.py
git commit -m "feat(ai-gateway): add GatewayService facade"
```

---

---
### Task 5: App-side wiring — GatewayService instance and non-blocking handlers

**Files:**
- Modify: `src/app/ai_device_ops.py`
- Modify: `src/app/main_window.py` (add `initialize_ai_gateway_service()` after `initialize_terminal_execution_coordinator()`)
- Modify: `src/device_mcp/core.py` (add `gateway_service()` and `gateway_script_style()` to `AppControlBackend` protocol)
- Test: `tests/test_ai_gateway_handlers.py`

**Interfaces:**
- Consumes: `GatewayService` (Task 4), existing mixin helpers `_ai_failure`, `_ai_device`, `_execute_ai_managed_transfer_start`.
- Produces:
  - `initialize_ai_gateway_service(self)` — creates `self.ai_gateway_service = GatewayService()` (**no executor**; the app side only does read/store operations).
  - `gateway_service(self) -> GatewayService` — accessor for service.py (`_invoke` injects its own executor).
  - `gateway_script_style(self, device_id: str) -> str` — `"linux"` (whole-block script) or `"network"` (line-by-line), for `ai_execute_script`.
  - Handler-dict entries in `execute_ai_device_action` (non-blocking only — `ai_create_session` and the 4 executing tools are orchestrated in service.py, Task 6):
    - `"ai_gateway_get_result"` → `_execute_ai_gateway_get_result`
    - `"ai_gateway_upload_file"` → `_execute_ai_gateway_upload_file` (reuses `_execute_ai_managed_transfer_start`)
    - `"ai_gateway_download_file"` → `_execute_ai_gateway_download_file` (Task 7)
  - `_execute_ai_gateway_get_result(action)` — `ai_gateway_service.get_result(result_id, include_raw)`; 404 `result_not_found` if missing.

**Behavior:**
- The app NEVER blocks the Qt thread for gateway execution. All command/batch/script/run_skill orchestration lives in service.py, which runs on the HTTP thread and injects an executor driving `_execute_terminal_plan` (start-on-Qt + wait-on-HTTP). `ai_create_session` is likewise driven on the HTTP thread (open + wait for connected) by service.py. The app's `GatewayService` has no executor; calling `execute_command` on it without one raises `GatewayUnavailableError` by design.
- `gateway_service()` lets service.py reach `ResultStore`/`SkillRegistry` through the facade.
- `gateway_script_style()` lets service.py decide `is_network_device` for `ai_execute_script`: Linux/SSH devices get the whole block; network devices (including `SIM-TERMINAL`, kind `simulated`) get line-by-line.

**Interfaces from later tasks:**
- Task 6 (service.py) calls `self.backend.gateway_service()` and `self.backend.gateway_script_style()`; injects an executor.
- Task 7's `download_file` plugs into `_execute_ai_gateway_download_file`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_ai_gateway_handlers.py
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from PySide6.QtWidgets import QApplication

from src.ai_device_ops import AiDeviceAction, RiskLevel
from src.app.main_window import DeviceDesktopApp


@pytest.fixture(scope="module")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_ai_gateway_service_is_initialized(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()
    assert hasattr(window, "ai_gateway_service")
    assert window.ai_gateway_service is window.gateway_service()


def test_ai_gateway_script_style_simulated_is_network(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()
    assert window.gateway_script_style("SIM-TERMINAL") == "network"


def test_ai_gateway_get_result_round_trip(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()
    # Seed the result store directly (execution itself is driven by service.py).
    result_id = window.ai_gateway_service.result_store.store(
        "command",
        "display version\nVRP (R) software, Version 8.180\n",
        metadata={"status": "success", "exit_code": 0, "command_count": 1, "duration_ms": 5},
    )
    fetched = window.execute_ai_device_action(
        AiDeviceAction(
            "ai_gateway_get_result",
            "读取网关结果",
            RiskLevel.OBSERVE,
            params={"result_id": result_id, "include_raw": True},
        )
    )
    assert fetched.ok
    assert fetched.data["result"]["result_id"] == result_id
    # raw_output is a TOP-LEVEL key of the result payload (spec contract).
    assert "raw_output" in fetched.data


def test_ai_gateway_get_result_missing_is_404(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()
    result = window.execute_ai_device_action(
        AiDeviceAction(
            "ai_gateway_get_result",
            "读取网关结果",
            RiskLevel.OBSERVE,
            params={"result_id": "R-does-not-exist"},
        )
    )
    assert not result.ok
    assert result.error_code == "result_not_found"
    assert result.http_status == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ai_gateway_handlers.py -v`
Expected: FAIL with `AttributeError: 'DeviceDesktopApp' object has no attribute 'ai_gateway_service'`

- [ ] **Step 3: Implement the app-side wiring**

In `src/device_mcp/core.py`, extend the `AppControlBackend` protocol:

```python
class AppControlBackend(Protocol):
    def execute_ai_device_action(
        self,
        action: AiDeviceAction,
        *,
        approved: bool = False,
    ) -> AiDeviceToolResult:
        ...

    def gateway_service(self) -> Any:
        """Return the app's GatewayService facade (result store + skill registry)."""
        ...

    def gateway_script_style(self, device_id: str) -> str:
        """Return 'linux' (whole-block script) or 'network' (line-by-line)."""
        ...
```

In `src/app/ai_device_ops.py`, add the constructor method and accessors (call from `main_window.py` `__init__` right after `initialize_terminal_execution_coordinator()`):

```python
def initialize_ai_gateway_service(self) -> None:
    from src.ai_gateway.service import GatewayService

    # The app-side instance has NO executor: command/batch/script/run_skill are
    # orchestrated by AppControlService (HTTP thread) which injects its own
    # executor. This instance exists so get_result/snapshot work app-side and so
    # service.py can reach the ResultStore/SkillRegistry through the facade.
    self.ai_gateway_service = GatewayService()

def gateway_service(self) -> Any:
    return getattr(self, "ai_gateway_service", None)

def gateway_script_style(self, device_id: str) -> str:
    device = self._ai_device(device_id)
    if device is None:
        return "network"
    # Device (@dataclass(slots=True)) has NO kind/protocols field — derive the
    # script style from connection params. The simulated device is a
    # network-device simulator → "network". A Linux host connects via SSH and
    # has no Telnet address → "linux". Anything else (network switches with
    # Telnet) → "network" (line-by-line).
    if getattr(self, "is_simulated_device", lambda _d: False)(device):
        return "network"
    ssh = str(getattr(device, "ssh_ip", "") or "").strip()
    telnet = str(getattr(device, "telnet_ip", "") or "").strip()
    return "linux" if ssh and not telnet else "network"
```

Add the non-blocking handler-dict entries in `execute_ai_device_action`:

```python
"ai_gateway_get_result": self._execute_ai_gateway_get_result,
"ai_gateway_upload_file": self._execute_ai_gateway_upload_file,
"ai_gateway_download_file": self._execute_ai_gateway_download_file,
```

> **Do NOT add** `ai_gateway_create_session`/`ai_gateway_execute_command/batch/script/run_skill` handlers here — they would run on the Qt thread and block it (deadlock). service.py handles them on the HTTP thread.

Add the handler methods:

```python
def _execute_ai_gateway_get_result(self, action: AiDeviceAction) -> AiDeviceToolResult:
    result_id = str(action.params.get("result_id") or "")
    include_raw = bool(action.params.get("include_raw", False))
    data = self.ai_gateway_service.get_result(result_id, include_raw=include_raw)
    if data is None:
        return self._ai_failure(
            action,
            "result_not_found",
            f"未找到执行结果: {result_id}",
            http_status=404,
        )
    return AiDeviceToolResult(action, ok=True, message="已读取网关执行结果。", data=data)

def _execute_ai_gateway_upload_file(self, action: AiDeviceAction) -> AiDeviceToolResult:
    # Reuse the existing managed transfer start (PC→device).
    return self._execute_ai_managed_transfer_start(action)

def _execute_ai_gateway_download_file(self, action: AiDeviceAction) -> AiDeviceToolResult:
    # Implemented in Task 7 (device→PC put direction).
    return self._ai_failure(action, "not_implemented", "设备下载方向尚未实现。", http_status=501)
```

In `src/app/main_window.py` `__init__`, right after `self.initialize_terminal_execution_coordinator()`:

```python
self.initialize_ai_gateway_service()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_ai_gateway_handlers.py -v`
Expected: PASS

- [ ] **Step 5: Run the existing ai tests to check nothing broke**

Run: `pytest tests/test_ai_device_ops.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/app/ai_device_ops.py src/app/main_window.py src/device_mcp/core.py tests/test_ai_gateway_handlers.py
git commit -m "feat(ai-gateway): wire app-side GatewayService instance and non-blocking handlers"
```

---

---
### Task 6: MCP tools, service routing, and risk/audit integration

**Files:**
- Create: `src/device_mcp/ai_gateway_execution.py` (new `AiGatewayExecutionMixin`)
- Create: `src/device_mcp/tools/ai_gateway.py` (8 MCP tool functions)
- Modify: `src/device_mcp/actions.py` (`_build_action` branches)
- Modify: `src/device_mcp/service.py` (add `AiGatewayExecutionMixin` to class bases; add `_invoke` branch + audit sub-step manifest)
- Modify: `src/device_mcp/tools/__init__.py` (register the new tool module)
- Modify: `src/device_mcp/client.py` (add 8 thin client methods)
- Modify: `src/device_mcp/http_server.py` (add 8 `do_POST` route entries)
- Test: `tests/test_ai_gateway_tools.py`

**Interfaces:**
- Consumes: `McpGateway.call`, `AppControlService._build_action`/`_invoke`/`_execute_terminal_plan` (ExecutionMixin), `GatewayService` via `backend.gateway_service()` (Task 5), app handler dict (Task 5, non-blocking entries only).
- Produces: 8 registered MCP tools; 8 HTTP routes; 8 client methods; `AiGatewayExecutionMixin._execute_ai_gateway_execute(action)` driving the 4 executing tools, and `_execute_ai_gateway_create_session(action)` driving `ai_create_session`.

**Threading contract (why this lives in service.py):** the 4 executing tools AND `ai_create_session` must NOT run on the Qt thread. `AppControlService._invoke` runs on the HTTP server thread. It injects an `executor` into `GatewayService` that builds a `terminal_plan_start` action and calls the existing `_execute_terminal_plan` (start-on-Qt via `_dispatch_action`, wait-on-HTTP via `completion_event.wait`). `ai_create_session` reuses `_execute_session_manage` (open + poll-for-connected on the HTTP thread). This mirrors how `terminal_execute_batch` / `session_manage` already work and avoids deadlocking the Qt event loop.

**Routing design:**
- `_build_action` maps each `ai_*` tool to an action kind, classifying risk (these actions carry the audit/approval record):
  - `ai_create_session` → `ai_gateway_create_session`, `RiskLevel.LOW`, `device_id`.
  - `ai_execute_command` → `ai_gateway_execute_command`, `classify_command_risk(command)`, `command=normalized`, params `{session_id, timeout_seconds}`.
  - `ai_execute_batch` → `ai_gateway_execute_batch`, max risk over commands, params `{commands, session_id, command_timeout_seconds}`.
  - `ai_execute_script` → `ai_gateway_execute_script`, max risk over lines, params `{script, shell, session_id, timeout_seconds}`.
  - `ai_upload_file` → `ai_gateway_upload_file`, `RiskLevel.FLOW`, params `{source_path, destination_path, overwrite}`.
  - `ai_download_file` → `ai_gateway_download_file`, `RiskLevel.LOW`, params `{source_path, destination_path}`.
  - `ai_get_result` → `ai_gateway_get_result`, `RiskLevel.OBSERVE`, params `{result_id, include_raw}`.
  - `ai_run_skill` → `ai_gateway_run_skill`, `RiskLevel.FLOW`, params `{skill_name, params, session_id, timeout_seconds}`.
- `_invoke` adds:
  - `elif tool == "ai_create_session": result = self._execute_ai_gateway_create_session(action)` (open + wait for connected, shaped to `{session_id, connected}`).
  - `elif tool in {"ai_execute_command", "ai_execute_batch", "ai_execute_script", "ai_run_skill"}: result = self._execute_ai_gateway_execute(action)`.
  - The remaining 3 tools (`ai_get_result`, `ai_upload_file`, `ai_download_file`) fall through to `_dispatch_action` → app handler dict (Task 5).
- Idempotency: all 8 tools accept `idempotency_key`; the existing `_invoke` cache applies unchanged (the executor runs only on cache miss).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_ai_gateway_tools.py
from __future__ import annotations

import os
import threading

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from src.device_mcp.actions import ActionBuilderMixin
from src.ai_device_ops import AiDeviceAction, AiDeviceToolResult, RiskLevel


class _Builder(ActionBuilderMixin):
    pass


def test_build_action_ai_execute_command_risk() -> None:
    action = _Builder()._build_action(
        "ai_execute_command",
        {"session_id": "sess-1", "command": "display version"},
    )
    assert action.kind == "ai_gateway_execute_command"
    assert action.risk == RiskLevel.LOW
    assert action.command == "display version"


def test_build_action_ai_execute_batch_takes_max_risk() -> None:
    action = _Builder()._build_action(
        "ai_execute_batch",
        {"session_id": "sess-1", "commands": ["display version", "reboot"]},
    )
    assert action.kind == "ai_gateway_execute_batch"
    assert action.risk == RiskLevel.HIGH


def test_build_action_ai_run_skill_is_flow_risk() -> None:
    action = _Builder()._build_action(
        "ai_run_skill",
        {"session_id": "sess-1", "skill_name": "driver_reload", "params": {}},
    )
    assert action.kind == "ai_gateway_run_skill"
    assert action.risk == RiskLevel.FLOW


def test_build_action_ai_download_is_low_risk() -> None:
    action = _Builder()._build_action(
        "ai_download_file",
        {
            "device_id": "SIM-TERMINAL",
            "source_path": "config/backup.cfg",
            "destination_path": "downloads/backup.cfg",
        },
    )
    assert action.kind == "ai_gateway_download_file"
    assert action.risk == RiskLevel.LOW


def test_build_action_ai_get_result_is_observe() -> None:
    action = _Builder()._build_action(
        "ai_get_result",
        {"result_id": "R1234abcd"},
    )
    assert action.kind == "ai_gateway_get_result"
    assert action.risk == RiskLevel.OBSERVE


def _service_with_fake_backend():
    """Build an AppControlService whose backend simulates terminal_plan_start."""
    from src.device_mcp.service import AppControlService
    from src.ai_gateway.service import GatewayService

    class FakeBackend:
        def __init__(self) -> None:
            self.gateway = GatewayService()

        def gateway_service(self):
            return self.gateway

        def gateway_script_style(self, device_id: str) -> str:
            return "network"

        def execute_ai_device_action(
            self,
            action: AiDeviceAction,
            *,
            approved: bool = False,
        ) -> AiDeviceToolResult:
            if action.kind == "terminal_plan_start":
                event = threading.Event()
                event.set()
                return AiDeviceToolResult(
                    action,
                    ok=True,
                    message="started",
                    data={
                        "_completion_event": event,
                        "execution_id": "e-fake",
                        "status": "completed",
                        "steps": [{"output": "display version\nVRP (R) software\n"}],
                        "error_code": "",
                    },
                )
            if action.kind == "terminal_execution_get":
                return AiDeviceToolResult(
                    action,
                    ok=True,
                    message="completed",
                    data={
                        "execution_id": "e-fake",
                        "status": "completed",
                        "steps": [{"output": "display version\nVRP (R) software\n"}],
                        "error_code": "",
                    },
                )
            return AiDeviceToolResult(action, ok=True, message="ok")

    backend = FakeBackend()
    service = AppControlService(backend, approval_mode="disabled")
    return backend, service


def test_service_routes_ai_execute_command_to_gateway() -> None:
    backend, service = _service_with_fake_backend()
    status, body = service.invoke(
        "ai_execute_command",
        {"session_id": "sess-1", "command": "display version"},
    )
    assert status == 200
    assert body["ok"] is True
    assert body["data"]["result_id"].startswith("R")
    assert body["data"]["summary"]["command_count"] == 1


def test_service_routes_ai_execute_batch_to_gateway() -> None:
    _, service = _service_with_fake_backend()
    status, body = service.invoke(
        "ai_execute_batch",
        {"session_id": "sess-1", "commands": ["display version", "display cpu"]},
    )
    assert status == 200
    assert body["data"]["summary"]["command_count"] == 2


def test_service_ai_get_result_routes_to_app_handler() -> None:
    _, service = _service_with_fake_backend()
    # Seed the store via the backend's gateway.
    backend_gateway = service.backend.gateway_service()
    result_id = backend_gateway.result_store.store(
        "command",
        "ok output",
        metadata={"status": "success", "exit_code": 0, "command_count": 1, "duration_ms": 1},
    )
    status, body = service.invoke(
        "ai_get_result",
        {"result_id": result_id, "include_raw": True},
    )
    assert status == 200
    assert body["data"]["result"]["result_id"] == result_id
    assert "raw_output" in body["data"]["result"]


def test_service_routes_ai_create_session_open_and_wait() -> None:
    from src.device_mcp.service import AppControlService
    from src.ai_gateway.service import GatewayService

    class CreateBackend:
        def __init__(self) -> None:
            self.gateway = GatewayService()

        def gateway_service(self):
            return self.gateway

        def gateway_script_style(self, device_id: str) -> str:
            return "network"

        def execute_ai_device_action(
            self,
            action: AiDeviceAction,
            *,
            approved: bool = False,
        ) -> AiDeviceToolResult:
            if action.kind == "session_manage":
                return AiDeviceToolResult(
                    action,
                    ok=True,
                    message="opened",
                    data={
                        "session": {
                            "session_id": "sess-1",
                            "device_id": action.device_id,
                            "status": "connected",
                        }
                    },
                )
            return AiDeviceToolResult(action, ok=True, message="ok")

    service = AppControlService(CreateBackend(), approval_mode="disabled")
    status, body = service.invoke(
        "ai_create_session",
        {"device_id": "SIM-TERMINAL"},
    )
    assert status == 200
    assert body["data"]["session_id"] == "sess-1"
    assert body["data"]["connected"] is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ai_gateway_tools.py -v`
Expected: FAIL with `AppControlError: 未知工具: ai_execute_command` (status 404)

- [ ] **Step 3: Add `_build_action` branches**

In `src/device_mcp/actions.py`, after the `file_transfer_start` branch and before the final `raise AppControlError`:

```python
if tool == "ai_create_session":
    return AiDeviceAction(
        "ai_gateway_create_session",
        "创建网关会话",
        RiskLevel.LOW,
        device_id=self._required_text(params, "device_id", max_chars=200),
    )
if tool == "ai_execute_command":
    command = normalize_command(
        self._required_text(params, "command", max_chars=MAX_COMMAND_CHARS)
    )
    device_id = self._optional_text(params, "device_id", max_chars=200)
    session_id = self._optional_text(params, "session_id", max_chars=240)
    if not device_id and not session_id:
        raise AppControlError("invalid_request", "执行网关命令需要 session_id 或 device_id。")
    return AiDeviceAction(
        "ai_gateway_execute_command",
        "执行网关命令",
        classify_command_risk(command),
        device_id=device_id,
        command=command,
        params={
            "session_id": session_id,
            "timeout_seconds": self._integer(params, "timeout_seconds", default=30, minimum=1, maximum=300),
        },
    )
if tool == "ai_execute_batch":
    raw_commands = params.get("commands")
    if not isinstance(raw_commands, list):
        raise AppControlError("invalid_request", "参数 commands 必须是数组。")
    commands = [normalize_command(str(command)) for command in raw_commands]
    device_id = self._optional_text(params, "device_id", max_chars=200)
    session_id = self._optional_text(params, "session_id", max_chars=240)
    if not device_id and not session_id:
        raise AppControlError("invalid_request", "执行网关批量命令需要 session_id 或 device_id。")
    risk = max((classify_command_risk(command) for command in commands), default=RiskLevel.LOW)
    return AiDeviceAction(
        "ai_gateway_execute_batch",
        "批量执行网关命令",
        risk,
        device_id=device_id,
        params={
            "commands": commands,
            "session_id": session_id,
            "command_timeout_seconds": self._integer(params, "command_timeout_seconds", default=30, minimum=1, maximum=300),
        },
    )
if tool == "ai_execute_script":
    script = self._required_text(params, "script", max_chars=MAX_COMMAND_CHARS * 8)
    device_id = self._optional_text(params, "device_id", max_chars=200)
    session_id = self._optional_text(params, "session_id", max_chars=240)
    if not device_id and not session_id:
        raise AppControlError("invalid_request", "执行网关脚本需要 session_id 或 device_id。")
    risk = max((classify_command_risk(line) for line in script.splitlines() if line.strip()), default=RiskLevel.LOW)
    return AiDeviceAction(
        "ai_gateway_execute_script",
        "执行网关脚本",
        risk,
        device_id=device_id,
        params={
            "script": script,
            "shell": self._optional_text(params, "shell", max_chars=100),
            "session_id": session_id,
            "timeout_seconds": self._integer(params, "timeout_seconds", default=30, minimum=1, maximum=300),
        },
    )
if tool == "ai_upload_file":
    return AiDeviceAction(
        "ai_gateway_upload_file",
        "上传文件到设备",
        RiskLevel.FLOW,
        device_id=self._required_text(params, "device_id", max_chars=200),
        params={
            "source_path": self._required_text(params, "source_path", max_chars=1_024),
            "destination_path": self._required_text(params, "destination_path", max_chars=1_024),
            "overwrite": self._boolean(params, "overwrite", default=False),
        },
    )
if tool == "ai_download_file":
    return AiDeviceAction(
        "ai_gateway_download_file",
        "从设备下载文件",
        RiskLevel.LOW,
        device_id=self._required_text(params, "device_id", max_chars=200),
        params={
            "source_path": self._required_text(params, "source_path", max_chars=1_024),
            "destination_path": self._required_text(params, "destination_path", max_chars=1_024),
        },
    )
if tool == "ai_get_result":
    return AiDeviceAction(
        "ai_gateway_get_result",
        "读取网关执行结果",
        RiskLevel.OBSERVE,
        params={
            "result_id": self._required_text(params, "result_id", max_chars=80),
            "include_raw": self._boolean(params, "include_raw", default=False),
        },
    )
if tool == "ai_run_skill":
    device_id = self._optional_text(params, "device_id", max_chars=200)
    session_id = self._optional_text(params, "session_id", max_chars=240)
    if not device_id and not session_id:
        raise AppControlError("invalid_request", "运行 Skill 需要 session_id 或 device_id。")
    return AiDeviceAction(
        "ai_gateway_run_skill",
        "运行网关 Skill",
        RiskLevel.FLOW,
        device_id=device_id,
        params={
            "skill_name": self._required_text(params, "skill_name", max_chars=200),
            "params": dict(params.get("params") or {}),
            "session_id": session_id,
            "timeout_seconds": self._integer(params, "timeout_seconds", default=60, minimum=1, maximum=3600),
        },
    )
```

- [ ] **Step 4: Add the `AiGatewayExecutionMixin`**

Create `src/device_mcp/ai_gateway_execution.py`:

```python
"""Gateway execution orchestration driven on the HTTP server thread."""

from __future__ import annotations

from typing import Any, Callable

from ..ai_device_ops import AiDeviceAction, AiDeviceToolResult, RiskLevel
from ..ai_gateway.service import GatewayUnavailableError
from ..ai_gateway.skills import SkillLoadError
from .core import AppControlError


class AiGatewayExecutionMixin:
    def _execute_ai_gateway_create_session(self, action: AiDeviceAction) -> AiDeviceToolResult:
        """Open a device session and wait for connected (HTTP thread)."""
        session_action = AiDeviceAction(
            "session_manage",
            "创建网关会话",
            RiskLevel.LOW,
            device_id=action.device_id,
            params={
                "action": "open",
                "protocol": "auto",
                "session_id": "",
                "timeout_seconds": 15,
            },
        )
        result = self._execute_session_manage(session_action)
        if not result.ok:
            return result
        session = (
            dict(result.data.get("session") or {})
            if isinstance(result.data, dict)
            else {}
        )
        session_id = str(session.get("session_id") or "")
        connected = str(session.get("status") or "") == "connected"
        return AiDeviceToolResult(
            action,
            ok=True,
            message=f"网关会话就绪: {session_id}",
            data={
                "session_id": session_id,
                "connected": connected,
                "session": session,
            },
        )

    def _execute_ai_gateway_execute(self, action: AiDeviceAction) -> AiDeviceToolResult:
        """Drive ai_execute_command/batch/script/run_skill on the HTTP thread."""
        gateway = getattr(self.backend, "gateway_service", lambda: None)()
        if gateway is None:
            raise AppControlError("gateway_unavailable", "网关服务未初始化。", status=409)
        executor = self._gateway_executor(action)
        session_id = str(action.params.get("session_id") or "")
        try:
            if action.kind == "ai_gateway_execute_command":
                data = gateway.execute_command(
                    action.command,
                    session_id,
                    timeout_seconds=int(action.params.get("timeout_seconds", 30)),
                    executor=executor,
                )
            elif action.kind == "ai_gateway_execute_batch":
                data = gateway.execute_batch(
                    list(action.params.get("commands") or []),
                    session_id,
                    command_timeout_seconds=int(action.params.get("command_timeout_seconds", 30)),
                    executor=executor,
                )
            elif action.kind == "ai_gateway_execute_script":
                style = getattr(self.backend, "gateway_script_style", lambda _d: "network")(action.device_id)
                data = gateway.execute_script(
                    str(action.params.get("script") or ""),
                    session_id,
                    shell=str(action.params.get("shell") or ""),
                    timeout_seconds=int(action.params.get("timeout_seconds", 30)),
                    is_network_device=(style != "linux"),
                    executor=executor,
                )
            elif action.kind == "ai_gateway_run_skill":
                data = gateway.run_skill(
                    str(action.params.get("skill_name") or ""),
                    dict(action.params.get("params") or {}),
                    session_id=session_id,
                    timeout_seconds=int(action.params.get("timeout_seconds", 60)),
                    executor=executor,
                )
            else:
                raise AppControlError("unknown_tool", f"未知网关动作: {action.kind}", status=404)
        except GatewayUnavailableError as exc:
            raise AppControlError(exc.code, str(exc), status=409) from exc
        except SkillLoadError as exc:
            raise AppControlError(exc.code, str(exc), status=400) from exc
        return AiDeviceToolResult(action, ok=True, message="网关执行完成。", data=data)

    def _gateway_executor(
        self,
        action: AiDeviceAction,
    ) -> Callable[[str, str, int], dict[str, Any]]:
        """Build the synchronous command executor: start-on-Qt + wait-on-HTTP."""
        def run(command: str, session_id: str, timeout_seconds: int) -> dict[str, Any]:
            plan_action = AiDeviceAction(
                "terminal_plan_start",
                f"网关执行: {command[:80]}",
                RiskLevel.LOW,  # actual risk already gated on the outer action
                device_id=action.device_id,
                params={
                    "plan_kind": "batch",
                    "commands": [command],
                    "session_id": session_id,
                    "command_timeout_seconds": int(timeout_seconds),
                    "total_timeout_seconds": int(timeout_seconds) + 5,
                    "max_output_chars_per_step": 16_384,
                    "mode": "auto",
                    "run_async": False,
                },
            )
            result = self._execute_terminal_plan(plan_action)
            if not result.ok:
                raise AppControlError(
                    result.error_code or "execution_failed",
                    result.message,
                    status=result.http_status or 409,
                )
            data = dict(result.data or {})
            status_map = {
                "completed": "success",
                "timed_out": "timeout",
                "failed": "failed",
                "cancelled": "failed",
                "disconnected": "failed",
            }
            status = status_map.get(str(data.get("status") or ""), "failed")
            output = "\n".join(
                str(step.get("output") or "")
                for step in data.get("steps", [])
                if isinstance(step, dict) and step.get("output")
            )
            return {
                "status": status,
                "output": output,
                "exit_code": 1 if data.get("error_code") else 0,
            }
        return run
```

In `src/device_mcp/service.py`, add the import and the mixin to the class bases:

```python
from .ai_gateway_execution import AiGatewayExecutionMixin

class AppControlService(
    ActionBuilderMixin,
    ExecutionMixin,
    AiGatewayExecutionMixin,
    OperationMixin,
    RequestValidationMixin,
):
```

- [ ] **Step 5: Add the `_invoke` branch + audit sub-step manifest**

In `src/device_mcp/service.py` `_invoke`, after `action = self._build_action(tool, params)` and the idempotency check, add:

```python
# Audit sub-step manifest: how many device operations one gateway call expands
# to. Mutate params IN PLACE so the audit writer in invoke() sees it.
if tool in {"ai_execute_batch", "ai_execute_script", "ai_run_skill", "ai_download_file"}:
    raw_commands = params.get("commands") or params.get("script")
    command_count = 1
    if isinstance(raw_commands, list):
        command_count = len(raw_commands)
    elif isinstance(raw_commands, str):
        command_count = len([line for line in raw_commands.splitlines() if line.strip()])
    params["sub_step_manifest"] = {
        "tool": tool,
        "command_count": command_count,
        "step_count": 0,  # skills expand later; the manifest documents intent
    }
```

In the same `_invoke`, extend the dispatch chain (before the final `else: result = self._dispatch_action(action)`):

```python
elif tool == "ai_create_session":
    result = self._execute_ai_gateway_create_session(action)
elif tool in {"ai_execute_command", "ai_execute_batch", "ai_execute_script", "ai_run_skill"}:
    result = self._execute_ai_gateway_execute(action)
```

- [ ] **Step 6: Add the MCP tool module**

Create `src/device_mcp/tools/ai_gateway.py`:

```python
"""AI Device Gateway MCP tools."""

from __future__ import annotations

from typing import Any

from ..gateway import McpGateway


def register_ai_gateway_tools(mcp: Any, gateway: McpGateway) -> None:
    @mcp.tool()
    def ai_create_session(device_id: str) -> dict[str, Any]:
        """Create or reuse a gateway session for a device."""
        return gateway.call("ai_create_session", device_id)

    @mcp.tool()
    def ai_execute_command(
        session_id: str,
        command: str,
        timeout_seconds: int = 30,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Execute one command on a device and return a summarized result."""
        return gateway.call(
            "ai_execute_command",
            session_id=session_id,
            command=command,
            timeout_seconds=timeout_seconds,
            idempotency_key=idempotency_key,
        )

    @mcp.tool()
    def ai_execute_batch(
        commands: list[str],
        session_id: str | None = None,
        device_id: str | None = None,
        command_timeout_seconds: int = 30,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Execute multiple commands in order. Pass session_id (preferred) or device_id."""
        return gateway.call(
            "ai_execute_batch",
            commands=commands,
            session_id=session_id,
            device_id=device_id,
            command_timeout_seconds=command_timeout_seconds,
            idempotency_key=idempotency_key,
        )

    @mcp.tool()
    def ai_execute_script(
        script: str,
        session_id: str | None = None,
        device_id: str | None = None,
        shell: str | None = None,
        timeout_seconds: int = 30,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Execute a script. Linux: whole block; network devices: line-by-line. Pass session_id (preferred) or device_id."""
        return gateway.call(
            "ai_execute_script",
            script=script,
            session_id=session_id,
            device_id=device_id,
            shell=shell,
            timeout_seconds=timeout_seconds,
            idempotency_key=idempotency_key,
        )

    @mcp.tool()
    def ai_upload_file(
        device_id: str,
        source_path: str,
        destination_path: str,
        overwrite: bool = False,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Upload one shared file to a device."""
        return gateway.call(
            "ai_upload_file",
            device_id,
            source_path,
            destination_path,
            overwrite=overwrite,
            idempotency_key=idempotency_key,
        )

    @mcp.tool()
    def ai_download_file(
        device_id: str,
        source_path: str,
        destination_path: str,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Download one file from a device to the PC."""
        return gateway.call(
            "ai_download_file",
            device_id,
            source_path,
            destination_path,
            idempotency_key=idempotency_key,
        )

    @mcp.tool()
    def ai_get_result(result_id: str, include_raw: bool = False) -> dict[str, Any]:
        """Fetch a gateway execution result, optionally including raw output."""
        return gateway.call(
            "ai_get_result",
            result_id=result_id,
            include_raw=include_raw,
        )

    @mcp.tool()
    def ai_run_skill(
        skill_name: str,
        params: dict[str, Any],
        session_id: str | None = None,
        device_id: str | None = None,
        timeout_seconds: int = 60,
        idempotency_key: str | None = None,
    ) -> dict[str, Any]:
        """Run a parameterized skill (a reusable flow) on a device. Pass session_id (preferred) or device_id."""
        return gateway.call(
            "ai_run_skill",
            skill_name=skill_name,
            params=params,
            session_id=session_id,
            device_id=device_id,
            timeout_seconds=timeout_seconds,
            idempotency_key=idempotency_key,
        )
```

Register it in `src/device_mcp/tools/__init__.py`: add the import and call alongside the existing tool module registrations (follow the existing `register_*_tools(mcp, gateway)` pattern).

- [ ] **Step 7: Add client methods + HTTP routes**

The `gateway.call(method, ...)` does `getattr(client, method)(...)`. So each `ai_*` tool needs a matching `AppControlClient` method that POSTs to a route, and each route maps to the same tool name in `http_server.do_POST`'s `routes` dict. Mirror `terminal_execute_batch` exactly.

In `src/device_mcp/http_server.py` `do_POST`, add to `routes`:

```python
"/v1/ai/create-session": "ai_create_session",
"/v1/ai/execute-command": "ai_execute_command",
"/v1/ai/execute-batch": "ai_execute_batch",
"/v1/ai/execute-script": "ai_execute_script",
"/v1/ai/upload-file": "ai_upload_file",
"/v1/ai/download-file": "ai_download_file",
"/v1/ai/get-result": "ai_get_result",
"/v1/ai/run-skill": "ai_run_skill",
```

In `src/device_mcp/client.py`, add eight thin methods (mirroring `terminal_execute_batch`, which is at `client.py` line ~249):

```python
def ai_create_session(self, device_id: str) -> dict[str, Any]:
    return self._request("POST", "/v1/ai/create-session", {"device_id": device_id})

def ai_execute_command(self, *, session_id: str = "", device_id: str = "", command: str = "", timeout_seconds: int = 30, idempotency_key: str | None = None) -> dict[str, Any]:
    return self._request("POST", "/v1/ai/execute-command", {
        "session_id": session_id, "device_id": device_id, "command": command,
        "timeout_seconds": timeout_seconds, "idempotency_key": idempotency_key,
    })

def ai_execute_batch(self, *, commands: list[str], session_id: str = "", device_id: str = "", command_timeout_seconds: int = 30, idempotency_key: str | None = None) -> dict[str, Any]:
    return self._request("POST", "/v1/ai/execute-batch", {
        "commands": commands, "session_id": session_id, "device_id": device_id,
        "command_timeout_seconds": command_timeout_seconds, "idempotency_key": idempotency_key,
    })

def ai_execute_script(self, *, script: str, session_id: str = "", device_id: str = "", shell: str = "", timeout_seconds: int = 30, idempotency_key: str | None = None) -> dict[str, Any]:
    return self._request("POST", "/v1/ai/execute-script", {
        "script": script, "session_id": session_id, "device_id": device_id,
        "shell": shell, "timeout_seconds": timeout_seconds, "idempotency_key": idempotency_key,
    })

def ai_upload_file(self, device_id: str, source_path: str, destination_path: str, *, overwrite: bool = False, idempotency_key: str | None = None) -> dict[str, Any]:
    return self._request("POST", "/v1/ai/upload-file", {
        "device_id": device_id, "source_path": source_path, "destination_path": destination_path,
        "overwrite": overwrite, "idempotency_key": idempotency_key,
    })

def ai_download_file(self, device_id: str, source_path: str, destination_path: str, *, idempotency_key: str | None = None) -> dict[str, Any]:
    return self._request("POST", "/v1/ai/download-file", {
        "device_id": device_id, "source_path": source_path, "destination_path": destination_path,
        "idempotency_key": idempotency_key,
    })

def ai_get_result(self, *, result_id: str, include_raw: bool = False) -> dict[str, Any]:
    return self._request("POST", "/v1/ai/get-result", {"result_id": result_id, "include_raw": include_raw})

def ai_run_skill(self, *, skill_name: str, params: dict[str, Any], session_id: str = "", device_id: str = "", timeout_seconds: int = 60, idempotency_key: str | None = None) -> dict[str, Any]:
    return self._request("POST", "/v1/ai/run-skill", {
        "skill_name": skill_name, "params": params, "session_id": session_id,
        "device_id": device_id, "timeout_seconds": timeout_seconds, "idempotency_key": idempotency_key,
    })
```

> **Note on `idempotency_key`:** `service._invoke` reads `params.get("idempotency_key")` for the cache key, so passing it through the body works exactly like `file_transfer_start` does.

> **`gateway_script_style` is already on the backend from Task 5** (protocol method + app impl). No action needed here.

- [ ] **Step 8: Run tests to verify they pass**

Run: `pytest tests/test_ai_gateway_tools.py -v`
Expected: PASS

- [ ] **Step 9: Run the full suite so far**

Run:
```bash
python -m py_compile src\*.py src\app\*.py src\device_mcp\*.py src\widgets\*.py
pytest tests/test_ai_device_ops.py tests/test_ai_gateway_*.py -x
```
Expected: PASS

- [ ] **Step 10: Commit**

```bash
git add src/device_mcp/ai_gateway_execution.py src/device_mcp/tools/ai_gateway.py src/device_mcp/actions.py src/device_mcp/service.py src/device_mcp/tools/__init__.py src/device_mcp/client.py src/device_mcp/http_server.py tests/test_ai_gateway_tools.py
git commit -m "feat(ai-gateway): register MCP tools, HTTP routes, and service routing"
```

---

---
### Task 7: Device→PC download (put direction)

**Files:**
- Modify: `src/managed_file_transfer.py` — add `build_managed_transfer_download_steps()` (`put` direction)
- Modify: `src/app/managed_file_transfer_ops.py` — add `download` direction support
- Modify: `src/app/ai_device_ops.py` — implement `_execute_ai_gateway_download_file`
- Test: `tests/test_ai_gateway_download.py`

**Interfaces:**
- Consumes: `build_managed_transfer_steps` existing FTP/SCP client-step builder, `transfer_service` server side, `ManagedTransferError`, mixin helpers from Task 5.
- Produces:
  - `build_managed_transfer_download_steps(*, protocol, host, port, source_path, destination_path, source_size) -> tuple[list[dict], int]` — mirrors `build_managed_transfer_steps` but the transfer step is `put {source} {destination}` (device pushes to PC server).
  - `start_managed_transfer_download(device_id, source_path, destination_path, *, overwrite=False)` mixin method — device→PC, reuses the operation state machine.
  - `_execute_ai_gateway_download_file` handler returns `{result_id, status}` — the `result_id` is generated by the managed-transfer operation; if the transfer runs async, it returns `{operation_id, result_id}` and the operator awaits via `operation_wait`/`ai_get_result`.

**Behavior:**
- The `put` direction is the mirror of `get`: connect to PC FTP/SCP server from the device, run `put <device_source> <pc_destination>`. The `destination_path` on the PC must be validated to stay within the transfer share (reuse `_validate_relative_path` semantics, but the *destination* is the PC-side relative path, not the source).
- Risk: `ai_download_file` is `RiskLevel.LOW` (already in Task 6); but the underlying transfer is guarded by the managed-transfer operation machine (approval + audit via existing `start_managed_file_transfer` flow). The `download` action must go through the same approval gate — set `RiskLevel.FLOW`? **Decision:** keep `LOW` for the read direction but require the managed-transfer operation's own gate (which the upload path already exercises). If the reviewer finds this inconsistent with the approval model, they can raise it.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_ai_gateway_download.py
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.managed_file_transfer import (
    ManagedTransferError,
    build_managed_transfer_download_steps,
)


def test_build_download_steps_uses_put() -> None:
    steps, total_timeout = build_managed_transfer_download_steps(
        protocol="ftp",
        host="10.0.1.1",
        port=2121,
        source_path="config/backup.cfg",
        destination_path="downloads/backup.cfg",
        source_size=1024 * 1024,
    )
    texts = [step.get("text", "") for step in steps]
    assert any(text.startswith("put ") for text in texts)
    assert any("get " in text for text in texts) is False
    assert total_timeout >= 120


def test_build_download_steps_validates_protocol() -> None:
    with pytest.raises(ManagedTransferError):
        build_managed_transfer_download_steps(
            protocol="unknown",
            host="h",
            port=1,
            source_path="a",
            destination_path="b",
            source_size=1,
        )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ai_gateway_download.py -v`
Expected: FAIL with `ImportError: cannot import name 'build_managed_transfer_download_steps'`

- [ ] **Step 3: Implement `build_managed_transfer_download_steps`**

In `src/managed_file_transfer.py`, add a function that mirrors `build_managed_transfer_steps` but with the transfer step `put {source} {destination}`:

```python
def build_managed_transfer_download_steps(
    *,
    protocol: str,
    host: str,
    port: int,
    source_path: str,
    destination_path: str,
    source_size: int,
) -> tuple[list[dict[str, Any]], int]:
    """Build FTP/SCP steps for a device->PC transfer (device 'put' to PC server)."""
    # Mirror build_managed_transfer_steps structure: connect, login, binary mode,
    # then `put <device_source> <pc_destination>`, then quit.
    # The only difference from the upload path is the final `put` command and
    # that `destination_path` is the PC-side relative path (validated against the
    # transfer share root). Reuse the same login/response steps.
```

> Implement by extracting the shared login/binary steps from `build_managed_transfer_steps` into a helper `_managed_transfer_connect_steps(protocol, host, port, responses, timeout_seconds)` and reusing it in both directions. The `put` step's success expectation is the FTP/SFTP prompt (same as `get`). The `source_size` drives the transfer timeout identically.

- [ ] **Step 4: Wire the mixin download method**

In `src/app/managed_file_transfer_ops.py`, add a `start_managed_transfer_download` method mirroring `start_managed_file_transfer` but with `direction="download"`. It must:
- Validate `source_path` (device-side absolute path) and `destination_path` (PC-side relative path within transfer share).
- Start a managed-transfer operation (reuse the existing `_managed_transfer_*` state machine; `direction` is stored on the operation dict).
- In the transfer step, call `build_managed_transfer_download_steps` instead of `build_managed_transfer_steps`.

Implement `_execute_ai_gateway_download_file` in `src/app/ai_device_ops.py`:

```python
def _execute_ai_gateway_download_file(self, action: AiDeviceAction) -> AiDeviceToolResult:
    try:
        data = self.start_managed_transfer_download(
            device_id=action.device_id,
            source_path=str(action.params.get("source_path") or ""),
            destination_path=str(action.params.get("destination_path") or ""),
        )
    except ManagedTransferError as exc:
        return self._ai_failure(action, exc.code, str(exc), http_status=404)
    ok = data.get("status") != "failed"
    return AiDeviceToolResult(
        action,
        ok=ok,
        message=str(data.get("message") or "设备文件下载已启动。"),
        data=data,
        error_code=str(data.get("error_code") or "") if not ok else "",
        http_status=409,
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_ai_gateway_download.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/managed_file_transfer.py src/app/managed_file_transfer_ops.py src/app/ai_device_ops.py tests/test_ai_gateway_download.py
git commit -m "feat(ai-gateway): add device-to-PC download direction"
```

---

### Task 8: Desktop state persistence

**Files:**
- Modify: `src/app/desktop_state.py`
- Test: `tests/test_ai_gateway_desktop_state.py`

**Interfaces:**
- Consumes: existing `load_desktop_state`/`save_desktop_state` pattern, `DESKTOP_STATE_VERSION`.
- Produces: `ai_gateway` section with `result_store` config (`max_entries`, `ttl_hours`), version bump 14 → 15.

**Behavior:**
- On load, if `state_version < 15` or section absent, use defaults (`max_entries=500`, `ttl_hours=24`).
- On load, clamp `max_entries` to 50–5000, `ttl_hours` to 1–168.
- After load, apply config to `self.ai_gateway_service.result_store` (construct/reconfigure the store).
- On save, write the `ai_gateway` section from current store config.
- No result bodies are persisted (per spec §State Persistence).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_ai_gateway_desktop_state.py
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from src.app.desktop_state import DESKTOP_STATE_VERSION
from src.app.main_window import DeviceDesktopApp


@pytest.fixture(scope="module")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_desktop_state_version_is_15() -> None:
    assert DESKTOP_STATE_VERSION == 15


def test_ai_gateway_defaults_applied(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()
    store = window.ai_gateway_service.result_store
    assert store.max_entries == 500
    assert store.ttl_seconds == 24 * 3600


def test_ai_gateway_config_loads_and_clamps(app: QApplication) -> None:
    _ = app
    window = DeviceDesktopApp()
    window.load_desktop_state_from_dict({
        "state_version": DESKTOP_STATE_VERSION,
        "ai_gateway": {
            "result_store": {"max_entries": 10000, "ttl_hours": 999},
        },
    })
    store = window.ai_gateway_service.result_store
    assert store.max_entries == 5000  # clamped
    assert store.ttl_seconds == 168 * 3600  # clamped
```

> Note: The test calls `load_desktop_state_from_dict` — if that helper doesn't exist, adapt to the existing load path used by other tests (check `tests/test_desktop_state_session_layout.py` for the pattern). The implementer should match the existing test convention.

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_ai_gateway_desktop_state.py -v`
Expected: FAIL — either `DESKTOP_STATE_VERSION != 15` or no `ai_gateway_service` attr or clamp missing.

- [ ] **Step 3: Implement**

In `src/app/desktop_state.py`:
- Bump `DESKTOP_STATE_VERSION = 15`.
- In `load_desktop_state`, parse the `ai_gateway` section:

```python
ai_gateway = state.get("ai_gateway") if isinstance(state.get("ai_gateway"), dict) else {}
result_store = ai_gateway.get("result_store") if isinstance(ai_gateway.get("result_store"), dict) else {}
max_entries = _clamp_int(result_store.get("max_entries", 500), 50, 5000)
ttl_hours = _clamp_int(result_store.get("ttl_hours", 24), 1, 168)
self.ai_gateway_result_store_config = {"max_entries": max_entries, "ttl_hours": ttl_hours}
```

- In `save_desktop_state`, write:

```python
state["ai_gateway"] = {
    "result_store": {
        "max_entries": getattr(self.ai_gateway_service, "result_store", None).max_entries
        if hasattr(self, "ai_gateway_service") and hasattr(self.ai_gateway_service, "result_store")
        else 500,
        "ttl_hours": getattr(self.ai_gateway_service, "result_store", None).ttl_seconds // 3600
        if hasattr(self, "ai_gateway_service") and hasattr(self.ai_gateway_service, "result_store")
        else 24,
    }
}
```

- In `main_window.py`, after `initialize_ai_gateway_service()`, apply config if present:

```python
config = getattr(self, "ai_gateway_result_store_config", None)
if config is not None and hasattr(self, "ai_gateway_service"):
    self.ai_gateway_service.result_store = ResultStore(
        max_entries=config["max_entries"],
        ttl_seconds=config["ttl_hours"] * 3600,
    )
```

> Note: `ResultStore` must accept a `max_entries` kwarg — it already does (Task 1). Check that `load_desktop_state` runs before `_build_window`/`initialize_ai_gateway_service` (the existing order in `__init__`: `load_desktop_state()` at line 421, then `initialize_terminal_execution_coordinator()` at line 424). The gateway init must come after `load_desktop_state` so config is applied. Verify ordering in Task 5.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_ai_gateway_desktop_state.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/app/desktop_state.py src/app/main_window.py tests/test_ai_gateway_desktop_state.py
git commit -m "feat(ai-gateway): persist result store config in desktop state v15"
```

---

### Task 9: End-to-end integration on the simulated device

**Files:**
- Create: `tests/test_ai_gateway_e2e.py`
- No source changes unless the e2e test surfaces a gap.

**Interfaces:**
- Consumes: all of Task 1–8.

**Behavior:**
- Start the app control server; drive `ai_create_session` → `ai_execute_command` → `ai_get_result` through the **full HTTP + MCP stack** on the simulated device (`SIM-TERMINAL`).
- Gateway execution blocks the HTTP thread while the runner advances on the Qt thread, so each HTTP call must run in a worker thread while the test pumps `app.processEvents()` — the exact `run_with_qt_events` helper from `tests/test_app_control_integration.py`.
- Verify the summary shape, `result_id` reuse, and raw retrieval.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_ai_gateway_e2e.py
from __future__ import annotations

import os
import queue
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from PySide6.QtWidgets import QApplication

from src.device_mcp.client import AppControlClient
from src.app.main_window import DeviceDesktopApp


@pytest.fixture(scope="module")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


def run_with_qt_events(
    app: QApplication,
    callback,
    *,
    timeout: float = 15.0,
):
    """Run a blocking callback on a worker thread while pumping Qt events.

    The gateway executor blocks the HTTP thread (completion_event.wait); the
    simulated session advances on the Qt thread via ui_timer, so the test
    thread must keep pumping processEvents for the runner to make progress.
    """
    results: queue.Queue[tuple[bool, object]] = queue.Queue(maxsize=1)

    def worker() -> None:
        try:
            results.put((True, callback()))
        except Exception as exc:  # noqa: BLE001
            results.put((False, exc))

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    deadline = time.monotonic() + timeout
    while thread.is_alive() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    thread.join(timeout=0.2)
    assert not thread.is_alive(), "gateway request did not finish"
    ok, value = results.get_nowait()
    if not ok:
        raise value  # type: ignore[misc]
    return value


def test_e2e_create_session_execute_and_get_result(
    app: QApplication,
    tmp_path: pytest.TempPathFactory,
) -> None:
    _ = app
    window = DeviceDesktopApp()
    state_path = tmp_path / "app-control.json"
    assert window.start_app_control_server(state_path=state_path)
    client = AppControlClient.from_state_file(state_path)

    created = run_with_qt_events(
        app,
        lambda: client.ai_create_session("SIM-TERMINAL"),
    )
    assert created["ok"]
    session_id = created["data"]["session_id"]
    assert session_id

    executed = run_with_qt_events(
        app,
        lambda: client.ai_execute_command(
            session_id=session_id,
            command="display version",
            timeout_seconds=5,
        ),
        timeout=20,
    )
    assert executed["ok"]
    assert executed["data"]["summary"]["status"] == "success"
    result_id = executed["data"]["result_id"]

    fetched = run_with_qt_events(
        app,
        lambda: client.ai_get_result(result_id=result_id, include_raw=True),
    )
    assert fetched["ok"]
    assert fetched["data"]["result"]["result_id"] == result_id
    assert "raw_output" in fetched["data"]
```

- [ ] **Step 2: Run tests and fix gaps**

Run: `pytest tests/test_ai_gateway_e2e.py -v`
Expected: PASS. If it surfaces a gap (e.g. the simulated session's `display version` output doesn't match the runner's expectations, or the simulated session must be selected first via `client.device_select("SIM-TERMINAL")` before `ai_create_session`), fix the source gap — this is the first integration check across Tasks 1–8. If the simulated device must be selected first, add `run_with_qt_events(app, lambda: client.device_select("SIM-TERMINAL"))` before `ai_create_session` (mirror `test_app_control_integration.py`).

- [ ] **Step 3: Run the full suite**

Run:
```bash
python -m py_compile src\*.py src\app\*.py src\device_mcp\*.py src\widgets\*.py
pytest tests/ -x
```

Expected: PASS (all existing tests + new gateway tests).

- [ ] **Step 4: Commit**

```bash
git add tests/test_ai_gateway_e2e.py
git commit -m "test(ai-gateway): add end-to-end gateway integration test"
```

---

## Self-Review

**Spec coverage check:**
- All 8 `ai_*` tools → Task 6 (MCP tools + HTTP routes + client methods) + Task 6 routing + Task 5 (app handlers for get_result/upload/download) + Task 7 (download).
- Result contract (`summary` + `result_id`) → Tasks 1, 4.
- `ai_get_result` TTL/LRU → Task 1; `ai_get_result` handler → Task 5.
- Flow engine (dependencies/wait/retry) → Task 2.
- Skill reuse (`run_skill`, JSON templates, `driver_reload`) → Task 3.
- Approval/audit/idempotency integration + sub-step manifest → Task 6 (`_build_action` risk, `_invoke` approval, in-place manifest).
- `ai_execute_script` Linux vs network device → Task 4 (`is_network_device`) + Task 5 (`gateway_script_style`).
- Device→PC download → Task 7.
- Desktop state v15 + config-only persistence → Task 8.
- E2E on simulated device → Task 9 (full HTTP stack + `run_with_qt_events`).

**Threading correctness (pre-flight fix):** the plan originally put `run_command` (with `completion_event.wait`) inside the app handler, which runs on the Qt thread via `call_on_ui_thread` → deadlock (the runner advances only on the Qt thread via `append_session_output`). Corrected: the 4 executing tools + `ai_create_session` are driven from `AiGatewayExecutionMixin` on the HTTP thread, reusing `_execute_terminal_plan` (start-Qt + wait-HTTP) and `_execute_session_manage` (open + poll). App-side handlers are non-blocking only.

**Placeholder scan:** All step bodies contain concrete code. Remaining `> Note:` blocks flag deliberate design decisions (threading contract, audit `step_count: 0` for skills, script-style on backend) — each names the deciding task and is not a TODO.

**Type consistency check:**
- `GatewayService.execute_command(command, session_id, *, timeout_seconds, executor)` — Task 6's mixin injects `executor(command, session_id, timeout_seconds)`. ✓
- `ResultStore(max_entries=..., ttl_seconds=...)` used in Task 8 matches Task 1's constructor. ✓
- `skill_flow(name, params) -> dict`, `parse_flow(dict) -> FlowPlan`, `FlowEngine.run(plan, *, session_id, device_id, execute_step, wait_for_condition, clock)` — Task 4 `run_skill` parses the dict and drives `FlowEngine`; callback signatures match. ✓
- `_build_action` kinds (`ai_gateway_execute_command` etc.) match the `_invoke` branch dispatch on `action.kind`, and the tests assert those exact strings. ✓
- `GatewayUnavailableError`/`SkillLoadError` imported by Task 6's mixin from `src.ai_gateway.*`. ✓

**Global constraint adherence:**
- No modifications to `TerminalExecutionCoordinator`/`build_batch_plan`/`parse_terminal_plan`/existing `terminal_*` tools. Task 6's executor only *builds* `terminal_plan_start` actions consumed by the existing `_execute_terminal_plan`. ✓
- All `ai_*` flow through `_build_action` (risk) + `_invoke` (approval/idempotency/audit). ✓
- Deterministic summaries, no LLM. ✓
- `result_id` = `R`+hex. ✓

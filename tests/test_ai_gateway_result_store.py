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

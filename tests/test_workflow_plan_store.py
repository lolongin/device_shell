from __future__ import annotations

from device_tui.infrastructure.persistence.sqlite_desktop import SQLiteDesktopStore


def test_sqlite_workflow_plan_store_round_trip(tmp_path) -> None:
    store = SQLiteDesktopStore(tmp_path / "desktop.sqlite3")
    payload = {
        "plan_id": "plan-1",
        "status": "validated",
        "updated_at": "2026-08-23T00:00:00+00:00",
        "plan_hash": "sha256:test",
        "plan": {
            "plan_id": "plan-1",
            "objective": "read version",
            "target": {"device_id": "d1"},
            "steps": [],
        },
        "workflow": None,
    }
    store.upsert_plan(payload)
    assert store.list_plans() == [payload]

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from device_tui.application.ai.gateway.skills import SkillLoadError, SkillRegistry


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

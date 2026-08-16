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
            # Bundled skills are always available; a custom directory overlays them.
            for directory in (Path(BUNDLED_SKILLS_DIR), Path(self.skills_dir)):
                if not directory.is_dir():
                    continue
                for path in sorted(directory.glob("*.json")):
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

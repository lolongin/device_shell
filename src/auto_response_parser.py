"""Simple text parser for terminal automation rule authoring."""

from __future__ import annotations

from dataclasses import dataclass
import re


AUTO_RESPONSE_RULE_KINDS = {"capture", "manual_loop", "quick_send", "advanced"}


@dataclass(slots=True)
class ParsedAutoResponseRule:
    """Structured result parsed from one simple rule line."""

    kind: str
    name: str
    trigger_type: str
    pattern: str
    response_text: str
    loop_count: int = 1
    trigger_delay_ms: int = 0
    step_delay_ms: int = 0
    append_enter: bool = True
    once: bool = True


@dataclass(slots=True)
class AutoResponseRuleParseError:
    """A user-facing parser error with a stable line number."""

    message: str
    line_number: int = 1


@dataclass(slots=True)
class AutoResponseRuleParseResult:
    """Parser result that carries either a rule or an error."""

    rule: ParsedAutoResponseRule | None = None
    error: AutoResponseRuleParseError | None = None

    @property
    def ok(self) -> bool:
        return self.rule is not None and self.error is None


def normalize_auto_response_rule_kind(value: object) -> str:
    """Return a supported user-facing rule kind."""

    text = str(value or "").strip().lower().replace("-", "_")
    return text if text in AUTO_RESPONSE_RULE_KINDS else "capture"


def infer_auto_response_rule_kind(
    *,
    trigger_type: str,
    loop_count: int,
    steps_count: int,
) -> str:
    """Infer a safe kind for saved rules that do not persist one yet."""

    if trigger_type == "manual" and loop_count > 1:
        return "manual_loop"
    if steps_count > 1:
        return "advanced"
    return "capture"


def parse_simple_auto_response_rule(value: str) -> AutoResponseRuleParseResult:
    """Parse one concise rule line into terminal automation fields."""

    lines = [line.strip() for line in value.splitlines() if line.strip()]
    if not lines:
        return _error("规则内容不能为空。")
    if len(lines) > 1:
        return _error("简单写法一次只支持一条规则；多步骤请使用高级流程。", 2)
    line = lines[0]
    if "=>" not in line:
        return _error("规则缺少 =>，例如：看到 Password: => admin。")
    left, response_text = line.split("=>", 1)
    left = left.strip()
    response_text = response_text.strip()
    if not response_text:
        return _error("=> 右侧发送内容不能为空。")
    if not left:
        return _error("=> 左侧触发条件不能为空。")

    parsed = (
        _parse_capture(left, response_text)
        or _parse_connected(left, response_text)
        or _parse_delay(left, response_text)
        or _parse_manual_loop(left, response_text)
        or _parse_manual(left, response_text)
        or _parse_button(left, response_text)
    )
    if parsed is None:
        return _error("无法识别触发方式，请使用：看到、连接后、延时、手动、手动循环、按钮。")
    return AutoResponseRuleParseResult(rule=parsed)


def _parse_capture(left: str, response_text: str) -> ParsedAutoResponseRule | None:
    for prefix in ("看到", "see", "when"):
        if not _starts_with_keyword(left, prefix):
            continue
        pattern = _strip_keyword(left, prefix)
        if not pattern:
            return None
        pattern = _unquote(pattern)
        return ParsedAutoResponseRule(
            kind="capture",
            name=f"看到 {pattern}",
            trigger_type="match",
            pattern=pattern,
            response_text=response_text,
        )
    return None


def _parse_connected(left: str, response_text: str) -> ParsedAutoResponseRule | None:
    lowered = left.lower()
    if lowered not in {"连接后", "connected", "on connect", "connect"}:
        return None
    return ParsedAutoResponseRule(
        kind="capture",
        name="连接后执行",
        trigger_type="connected",
        pattern="",
        response_text=response_text,
    )


def _parse_delay(left: str, response_text: str) -> ParsedAutoResponseRule | None:
    match = re.fullmatch(r"(?:延时|delay)\s*(\d+)\s*ms", left, re.IGNORECASE)
    if match is None:
        return None
    delay_ms = max(0, int(match.group(1)))
    return ParsedAutoResponseRule(
        kind="capture",
        name=f"延时 {delay_ms}ms",
        trigger_type="delay",
        pattern="",
        response_text=response_text,
        trigger_delay_ms=delay_ms,
    )


def _parse_manual_loop(left: str, response_text: str) -> ParsedAutoResponseRule | None:
    match = re.fullmatch(
        r"(?:手动循环|manual\s+loop)\s*(\d+)\s*(?:次|times)?(?:\s*[,，]\s*(?:每|every)\s*(\d+)\s*ms)?",
        left,
        re.IGNORECASE,
    )
    if match is None:
        return None
    loop_count = max(1, min(10, int(match.group(1))))
    step_delay_ms = max(0, int(match.group(2) or 0))
    return ParsedAutoResponseRule(
        kind="manual_loop",
        name=f"手动循环 {loop_count} 次",
        trigger_type="manual",
        pattern="",
        response_text=response_text,
        loop_count=loop_count,
        step_delay_ms=step_delay_ms,
        once=False,
    )


def _parse_manual(left: str, response_text: str) -> ParsedAutoResponseRule | None:
    lowered = left.lower()
    if lowered not in {"手动", "manual"}:
        return None
    return ParsedAutoResponseRule(
        kind="manual_loop",
        name="手动执行",
        trigger_type="manual",
        pattern="",
        response_text=response_text,
        once=False,
    )


def _parse_button(left: str, response_text: str) -> ParsedAutoResponseRule | None:
    for prefix in ("按钮", "button"):
        if not _starts_with_keyword(left, prefix):
            continue
        name = _strip_keyword(left, prefix)
        if not name:
            return None
        name = _unquote(name)
        return ParsedAutoResponseRule(
            kind="quick_send",
            name=name,
            trigger_type="manual",
            pattern="",
            response_text=response_text,
            append_enter=False,
            once=False,
        )
    return None


def _starts_with_keyword(value: str, keyword: str) -> bool:
    if keyword.isascii():
        return value.lower().startswith(keyword.lower())
    return value.startswith(keyword)


def _strip_keyword(value: str, keyword: str) -> str:
    return value[len(keyword) :].strip()


def _unquote(value: str) -> str:
    text = value.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        return text[1:-1].strip()
    return text


def _error(message: str, line_number: int = 1) -> AutoResponseRuleParseResult:
    return AutoResponseRuleParseResult(
        error=AutoResponseRuleParseError(message=message, line_number=line_number)
    )

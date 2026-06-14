# Auto Response Rule Authoring Design

Date: 2026-06-14

## Goal

Reduce the effort required to create terminal automation rules while preserving
the current advanced capabilities. The editor should make three common intents
obvious:

- Automatically react when terminal output is captured.
- Manually start a rule that can keep running for a configured loop count.
- Send a simple command or control key with one button click.

The first implementation should use a hybrid editor: users pick a scenario,
write or edit a simple rule, and see the parsed workflow as visual steps.

## Current Context

The project already has:

- `AutoResponseRule` and `AutoResponseStep` in `src/auto_response.py`.
- Trigger fields for match, immediate, connected, delay, and manual rules.
- Loop count and trigger delay support.
- Quick send buttons through `TerminalQuickButton`.
- A web-based auto-response editor in `src/web/auto_response_editor.html`.
- Execution logic in `src/app/session_ops.py`.

The current model is powerful, but users must think in low-level fields:
patterns, responses, targets, step delays, append-enter behavior, trigger
types, max trigger counts, startup suppression, and loop count. That makes
simple rules feel more complex than they are.

## Recommended Approach

Implement a hybrid editor around a new user-facing "rule kind":

- `capture`: automatically captures terminal output and responds.
- `manual_loop`: starts from a button and can loop.
- `quick_send`: sends one action immediately.
- `advanced`: keeps the existing full workflow controls.

These kinds should map onto existing fields rather than replace the runtime
model. The existing execution engine remains the source of truth.

## User Experience

The editor opens with a compact scenario chooser:

- "看到内容就响应"
- "手动持续运行"
- "按一下发送"
- "高级流程"

Below the chooser, the editor shows a simple rule input tailored to the chosen
scenario.

Examples:

```text
看到 "Password:" => admin
看到 ">" => display version
手动循环 5 次，每 1000ms => display clock
按钮 "Ctrl+B" => Ctrl+B
连接后 => system-view
```

The right side keeps a flow preview:

```text
触发：匹配输出 "Password:"
动作：发送 admin + Enter
结束：命中一次后停止
```

For manual loop rules:

```text
触发：手动按钮
循环：5 次
动作：每 1000ms 发送 display clock + Enter
```

For quick-send rules:

```text
触发：按钮点击
动作：发送 Ctrl+B
```

Advanced controls stay available for target terminal, regex matching,
case sensitivity, max trigger count, per-action delay, append Enter,
startup trigger, and multi-step workflows.

## Data Model

Add an optional `kind` field to `AutoResponseRule`:

```python
kind: str = "capture"
```

Allowed values:

- `capture`
- `manual_loop`
- `quick_send`
- `advanced`

Serialization should persist `kind`. Deserialization should default older
saved rules safely:

- `trigger_type == "manual"` and `loop_count > 1` becomes `manual_loop`.
- A rule with one action and no output pattern can become `quick_send` only
  when loaded through quick-send migration logic. Existing auto-response rules
  should default to `capture` or `advanced` to avoid changing behavior.
- Multi-step rules default to `advanced`.
- Other rules default to `capture`.

`TerminalQuickButton` can stay for compatibility in the first pass. The UI may
render quick-send templates next to existing quick-send buttons, but the saved
format should not require immediate migration.

## Simple Rule Parser

Add a small parser in a focused helper module: `src/auto_response_parser.py`.

Supported first-pass forms:

```text
看到 "PATTERN" => RESPONSE
看到 PATTERN => RESPONSE
连接后 => RESPONSE
延时 1500ms => RESPONSE
手动 => RESPONSE
手动循环 5 次 => RESPONSE
手动循环 5 次，每 1000ms => RESPONSE
按钮 "NAME" => RESPONSE
按钮 NAME => RESPONSE
```

Parser output should be structured, not a partially built UI payload:

```python
ParsedAutoResponseRule(
    kind="capture",
    name="Password",
    trigger_type="match",
    pattern="Password:",
    response_text="admin",
    loop_count=1,
    trigger_delay_ms=0,
    step_delay_ms=0,
    append_enter=True,
)
```

Invalid input should return an error object with a precise message and line
number. The web editor can show that message under the simple rule field.

## Runtime Behavior

The execution path should keep using `AutoResponseRule` and
`AutoResponseStep`. The implementation should avoid duplicating rule execution
for each kind.

Expected mapping:

- `capture`: `trigger_type="match"`, non-empty first pattern.
- `manual_loop`: `trigger_type="manual"`, first step may have an empty pattern,
  `loop_count` controls repetition.
- `quick_send`: keeps using the direct-send click path. It should not run
  through background automation or toggle enabled state.
- `advanced`: no extra constraints.

When a manual rule is clicked, the main rule bar should run it instead of only
toggling enabled state. Capture rules keep toggle behavior.

## Editor Implementation

Update `src/web/auto_response_editor.html`:

- Add a scenario segmented control near the top.
- Add a simple rule textarea/input with examples for the selected kind.
- Keep the existing step cards as advanced controls.
- Show parser errors inline.
- Keep the flow preview visible and make it reflect both simple and advanced
  editing.
- Hide irrelevant fields for simple scenarios, but do not delete their values.
- Provide a "show advanced fields" affordance for escape hatches.

Update `AutoResponseRuleWebDialog` in `src/app/session_ops.py`:

- Include `kind` and `simpleRuleText` in the payload.
- Convert simple-rule payloads to existing `values_from_payload` output.
- Preserve existing payload handling for advanced workflows.

## Cleanup

`src/app/session_ops.py` currently contains duplicated definitions for
`parse_auto_response_steps` and `apply_auto_response_rules`. The implementation
should remove the obsolete duplicates or merge them before adding new behavior,
so future fixes land in one place.

## Testing

Add or extend tests in `tests/test_auto_response.py`:

- Simple parser handles capture rules.
- Simple parser handles connected rules.
- Simple parser handles delay rules.
- Simple parser handles manual loop rules.
- Simple parser handles quick-send rules.
- Parser returns useful errors for missing `=>` and empty response.
- `kind` serializes and deserializes.
- Existing saved rules without `kind` remain valid.
- Manual loop rules execute through the existing runtime.
- Quick-send behavior does not regress existing `TerminalQuickButton` tests.
- Web dialog payload round-trips `kind` and simple rule text.

Run:

```powershell
python -m py_compile src\*.py
pytest tests/test_auto_response.py
```

## Out Of Scope

- A natural-language AI rule writer.
- Full migration of `TerminalQuickButton` storage into `AutoResponseRule`.
- Device-specific template libraries.
- Background scheduling across disconnected sessions.
- Multi-rule dependency graphs.

## Acceptance Criteria

- A user can create an automatic capture rule from one simple line.
- A user can create a manual looping rule without touching pattern fields.
- A user can create or keep using one-click send buttons.
- Advanced users can still edit multi-step workflows.
- Existing saved rules load without behavior changes.
- Tests cover parsing, serialization, and runtime execution for the new kinds.

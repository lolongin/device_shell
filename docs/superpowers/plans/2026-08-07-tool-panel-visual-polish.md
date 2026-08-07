# Tool Panel Visual Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the dark "black blocks" behind bare labels in the three left-drawer tool panels (临时连接 / 文件传输 / 一键大包更换) and de-gray those panels by giving their cards translucent deep surfaces over the pure-black base, matching the Web home look.

**Architecture:** Two additive QSS blocks appended to `src/styles.py` immediately before the final `/* Global text selection */` block (so text-selection stays the last block, per `tests/test_text_selection_theme.py`). Block 1 makes every bare QLabel inside the tool panels transparent (fixing the black blocks caused by the global `QWidget { background: #020617 }` cascade). Block 2 overrides the tool-panel card fills to translucent deep colors so the `#020617` base shows through for a layered, Web-like depth. All existing rules are untouched.

**Tech Stack:** Qt QSS, Python, pytest.

## Global Constraints

(Values copied verbatim from `docs/superpowers/specs/2026-08-07-tool-panel-visual-polish-design.md`.)

- Additive-only CSS: do NOT edit existing rules in `src/styles.py`; only insert the two new blocks.
- `/* Global text selection */` must remain the **last** block in `APP_STYLE`. Both new blocks go immediately **before** it.
- Tool panels only: 临时连接 / 文件传输 / 一键大包更换 + their shared `navShell` shell card. Not the whole app.
- Border colors (`#243244`) and radii (12px) stay unchanged — only card fills become translucent.
- New blocks (verbatim):
  ```css
  /* Tool panel label transparency */
  QGroupBox#navShell QLabel,
  QFrame#temporaryFormCard QLabel,
  QFrame#temporaryProtocolCard QLabel,
  QFrame#temporaryDeviceCard QLabel,
  QFrame#transferConfigCard QLabel,
  QFrame#transferStatusCard QLabel {
      background: transparent;
  }

  /* Tool panel translucent surfaces */
  QGroupBox#navShell,
  QGroupBox#deviceDetailCard,
  QGroupBox#quickActionCard,
  QGroupBox#authCard {
      background: rgba(15, 23, 42, 0.66);
  }
  QFrame#temporaryFormCard,
  QFrame#transferConfigCard,
  QFrame#transferStatusCard {
      background: rgba(8, 16, 29, 0.72);
  }
  QFrame#temporaryProtocolCard {
      background: rgba(8, 16, 29, 0.78);
  }
  QFrame#temporaryProtocolCard:hover {
      background: rgba(15, 23, 42, 0.78);
  }
  QFrame#temporaryDeviceCard {
      background: rgba(15, 23, 42, 0.72);
  }
  QFrame#temporaryDeviceCard:hover {
      background: rgba(17, 28, 47, 0.78);
  }
  QFrame#serverCard:hover {
      background: rgba(15, 23, 42, 0.78);
  }
  QFrame#serverGroupHeader {
      background: rgba(15, 23, 42, 0.72);
  }
  QFrame#serverGroupHeader:hover {
      background: rgba(17, 28, 47, 0.78);
  }
  ```
- Full suite expectation: 510 passed / 3 known pre-existing failures (auto_response suggestion, temporary-panel cards, web-pages theme) — do NOT fix them; confirm no NEW failures.

---

### Task 1: Append tool-panel transparency + translucent-surface QSS

**Files:**
- Modify: `src/styles.py:3354-3356` (insert two blocks before `/* Global text selection */`)
- Test: `tests/test_tool_panel_theme.py` (NEW — this file)

**Interfaces:**
- Consumes: `APP_STYLE` from `src/styles.py`.
- Produces: `tests/test_tool_panel_theme.py` (theme-block assertions, terminal state).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_tool_panel_theme.py`:

```python
from __future__ import annotations

from src.styles import APP_STYLE


def test_tool_panel_label_transparency_block_present() -> None:
    assert "/* Tool panel label transparency */" in APP_STYLE
    block = APP_STYLE[APP_STYLE.index("/* Tool panel label transparency */") :]
    assert "QGroupBox#navShell QLabel," in block
    assert "background: transparent;" in block


def test_tool_panel_translucent_surfaces_block_present() -> None:
    assert "/* Tool panel translucent surfaces */" in APP_STYLE
    block = APP_STYLE[APP_STYLE.index("/* Tool panel translucent surfaces */") :]
    assert "QFrame#transferConfigCard," in block
    assert "background: rgba(8, 16, 29, 0.72);" in block
    assert "background: rgba(15, 23, 42, 0.66);" in block


def test_tool_panel_blocks_precede_text_selection() -> None:
    assert APP_STYLE.index("/* Tool panel label transparency */") < APP_STYLE.rindex(
        "/* Global text selection */"
    )
    assert APP_STYLE.index("/* Tool panel translucent surfaces */") < APP_STYLE.rindex(
        "/* Global text selection */"
    )
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_tool_panel_theme.py -v`
Expected: FAIL (blocks not present).

- [ ] **Step 3: Insert the two QSS blocks** (`src/styles.py`, between the end of the
  `/* Session manager panel */` block at line 3354 and `/* Global text selection */` at line 3356)

Insert exactly (immediately before `/* Global text selection */`):

```css
/* Tool panel label transparency */
QGroupBox#navShell QLabel,
QFrame#temporaryFormCard QLabel,
QFrame#temporaryProtocolCard QLabel,
QFrame#temporaryDeviceCard QLabel,
QFrame#transferConfigCard QLabel,
QFrame#transferStatusCard QLabel {
    background: transparent;
}

/* Tool panel translucent surfaces */
QGroupBox#navShell,
QGroupBox#deviceDetailCard,
QGroupBox#quickActionCard,
QGroupBox#authCard {
    background: rgba(15, 23, 42, 0.66);
}
QFrame#temporaryFormCard,
QFrame#transferConfigCard,
QFrame#transferStatusCard {
    background: rgba(8, 16, 29, 0.72);
}
QFrame#temporaryProtocolCard {
    background: rgba(8, 16, 29, 0.78);
}
QFrame#temporaryProtocolCard:hover {
    background: rgba(15, 23, 42, 0.78);
}
QFrame#temporaryDeviceCard {
    background: rgba(15, 23, 42, 0.72);
}
QFrame#temporaryDeviceCard:hover {
    background: rgba(17, 28, 47, 0.78);
}
QFrame#serverCard:hover {
    background: rgba(15, 23, 42, 0.78);
}
QFrame#serverGroupHeader {
    background: rgba(15, 23, 42, 0.72);
}
QFrame#serverGroupHeader:hover {
    background: rgba(17, 28, 47, 0.78);
}

/* Global text selection */
```

- [ ] **Step 4: Run the new theme tests**

Run: `pytest tests/test_tool_panel_theme.py -v`
Expected: PASS (all 3).

- [ ] **Step 5: Run the stylesheet regression tests**

Run: `pytest tests/test_text_selection_theme.py tests/test_session_layout_theme.py tests/test_ui_unification.py -q`
Expected: PASS (`/* Global text selection */` still the last block; earlier theme blocks unaffected).

Run: `pytest tests/test_session_credentials.py -k "style or theme" -q`
Expected: PASS (existing `APP_STYLE` substring assertions still hold; the two pre-existing failures in that file, `test_temporary_panel_uses_workspace_cards` and `test_web_pages_share_workspace_theme`, are out of scope).

- [ ] **Step 6: Verify the black-block fix by rendering the package-upgrade form**

Run:

```bash
timeout 90 python -c "
import os
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QGroupBox, QFormLayout, QLabel, QLineEdit, QHBoxLayout, QVBoxLayout, QWidget
from src.styles import APP_STYLE
app = QApplication([])
panel = QWidget()
panel.setObjectName('leftRail')
layout = QVBoxLayout(panel)
layout.setContentsMargins(0,0,8,0)
group = QGroupBox('一键大包更换')
group.setObjectName('navShell')
gl = QVBoxLayout(group)
form = QFormLayout()
form.setLabelAlignment(Qt.AlignRight)
row = QHBoxLayout()
row.addWidget(QLineEdit()); row.addWidget(QLineEdit())
form.addRow('系统包', row)
gl.addLayout(form)
layout.addWidget(group)
panel.setStyleSheet(APP_STYLE)
panel.show(); app.processEvents()
labels = panel.findChildren(QLabel)
for lbl in labels:
    print(lbl.text(), lbl.palette().color(lbl.backgroundRole()).name(), lbl.palette().brush(lbl.backgroundRole()).style())
panel.close()
"
```

Expected: the `系统包` label prints palette bg `#000000` (transparent) — NOT `#020617`.

- [ ] **Step 7: Full test suite**

Run: `pytest -q`
Expected: 510 passed / 3 failed — the 3 failures are the known pre-existing set:
- `tests/test_auto_response.py::test_terminal_command_suggestion_uses_history_and_defaults`
- `tests/test_session_credentials.py::test_temporary_panel_uses_workspace_cards`
- `tests/test_session_credentials.py::test_web_pages_share_workspace_theme`
These are unrelated to this plan (they assert on `auto_response_editor.html` / auto-response
suggestion content) and were failing before this plan began. Do NOT fix them; confirm your
change introduces no NEW failures.

- [ ] **Step 8: Commit**

```bash
git add src/styles.py tests/test_tool_panel_theme.py
git commit -m "style(tool-panels): translucent surfaces and transparent labels
"
```

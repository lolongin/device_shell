# Right Session Manager Upgrade — Design

Date: 2026-08-07
Status: Approved (user)

## Goal

The right-side "会话管理器" (session manager) panel is the only surface in the app
that renders with **zero** stylesheet rules — a default Windows white tree widget on a
`#020617` OLED dark UI. Upgrade it to the workspace theme and enrich its information
density with a two-column compact layout.

## Decisions (confirmed with user)

- Direction: **theme + information enrichment** (not just a reskin, not a layout redesign).
- Density: **compact enhancement** — connection-state dots and per-session metadata, still tight.
- Device/session iconography: **device icons + status dots** (device groups get a connection-tinted
  device icon; session rows keep their status dot).
- Approach (from the proposal): **B — theme + two-column compact metadata**.

## Current State (discovery)

- `build_session_manager_panel()` (`src/app/session_layout_ops.py:55-114`) builds the panel with
  these objectNames — **none of which have a single rule in `src/styles.py`**:
  `sessionManagerPanel`, `sessionManagerTitle`, `sessionManagerCount`, `sessionManagerCollapse`,
  `sessionManagerSearch`, `sessionManagerTree`, `sessionManagerStrip`, `sessionManagerExpand`.
- The tree is single-column (`QTreeWidget`, header hidden). `refresh_session_manager_tree()`
  (`:218-276`) sets col-0 text only: group = `f"{label} ({len(states)})"`, child = `state.title`.
- Both parent and child already set a **col-0 icon** (status dot via `_session_manager_dot_icon`),
  which existing tests assert is non-null (`tests/test_session_layout_manager.py:71-100`).
- Existing session data available: `state.kind` (`device`/`linux`/`serial`/`simulated` →
  `session_kind_label()` → 中文), `state.host`, `state.port`, `state.title`, and
  `_tab_connection_state()` → `connected`/`connecting`/`idle`/`error`.
- No code assumes the tree is single-column (no `columnCount` coupling for this tree).

## Design

### 1. Two-column tree with compact metadata (`src/app/session_layout_ops.py`)

- In `build_session_manager_panel`, call `self.session_manager_tree.setColumnCount(2)` once.
- `refresh_session_manager_tree()` col-0/col-1 changes:
  - **Device group (parent):** col0 = new device icon (connection-tinted) + bare device name
    (drop the `(n)` suffix from the name — the count moves to col1). col1 = session-count
    badge `str(len(states))` in muted text.
  - **Session child:** col0 = existing status dot + `state.title` (current session stays bold).
    col1 = `"协议 · host:port"` from `session_kind_label(state.kind)` + `state.host:state.port`,
    muted and truncated.
- **New icon** `_session_manager_device_icon(kind, color)`: 16×16, 1.7px stroke style matching
  `_activity_icon`, one glyph per `kind` (`device`/`linux`/`serial`/`simulated`), tinted by
  connection state. Parent color = green if any child `connected`, amber if any `connecting`,
  gray otherwise (mirrors the existing parent-dot aggregation).
- Both columns keep the existing status-dot / new device icons non-null (test constraint).

### 2. QSS theme layer (`src/styles.py`, additive)

New block `/* Session manager panel */`, appended before the final `/* Global text selection */`
block (the existing `test_text_selection_theme.py` requires text-selection to remain the last
block). Rules:

- `sessionManagerPanel`: transparent background (melts into `#020617`).
- `sessionManagerTitle`: `#f8fafc`, weight 700.
- `sessionManagerCount`: muted pill/counter text.
- `sessionManagerCollapse` / `sessionManagerExpand`: match the `activityRailButton` icon-button
  treatment (small, `#08101d` bg, `#243244` border, hover `#60a5fa`).
- `sessionManagerSearch`: inherits the already-unified `QLineEdit` surface (no extra rule needed,
  but keep the panel spacing tight).
- `sessionManagerTree`: `#020617` background, no frame, `::item` padding, hover `#111c2f`,
  selected `#24324a` / `#f8fafc`, muted secondary-column text, collapsed branch arrows hidden or
  hairline (use `QTreeView::branch` no-decoration or a minimal expander), `QHeaderView::section`
  transparent (hidden header still needs a rule to avoid default gradient).
- `sessionManagerStrip`: dark `#0f172a` narrow strip with hairline border.

All colors are existing workspace tokens (see `src/theme_tokens.py` / `design-system/MASTER.md`).
No new tokens.

### 3. Tests

- Existing `tests/test_session_layout_manager.py::test_tree_items_have_status_dot_icons` keeps
  passing (col-0 icons stay non-null).
- **New** in `tests/test_session_layout_manager.py`:
  - `test_tree_has_two_columns_with_session_metadata` — session row col1 contains protocol
    (`Telnet`/`SSH`/`串口`/`模拟`) and `host:port`; col0 has title + non-null icon.
  - `test_device_parent_column1_shows_session_count` — parent col1 text equals the session count.
- **New** `tests/test_session_layout_theme.py`:
  - `/* Session manager panel */` block exists in `APP_STYLE`.
  - Block sits before `/* Global text selection */` (same guarantee as the unification block).
  - Block contains `QTreeWidget#sessionManagerTree::item:selected` with `#24324a`.

### 4. Non-breaking contracts

- `main_splitter.count() == 3`, collapse/expand, context menu, search filter, collapse memory,
  and `session_kind_label()` / `_tab_connection_state()` reuse — all unchanged.
- Fully additive; `/* Global text selection */` stays the last `APP_STYLE` block.

## Files touched

- `src/app/session_layout_ops.py` — two-column tree, device icons, col-1 metadata.
- `src/styles.py` — additive `/* Session manager panel */` block before Global text selection.
- `tests/test_session_layout_manager.py` — two new tree tests.
- `tests/test_session_layout_theme.py` — NEW: theme-block assertions.

## Verification

- `python -m py_compile src\app\session_layout_ops.py src\styles.py`.
- `pytest tests/test_session_layout_manager.py tests/test_session_layout_theme.py -v` — all pass.
- Full suite: 494 passed / 3 known pre-existing failures (unchanged).
- Manual/`run`: right session manager shows dark tree, two columns (device icon+name / count /
  session dot+title / protocol·host:port), current session bold, device icon tints with connection.

## Out of scope

- Changing the splitter/stack/collapse architecture.
- New theme tokens (reuse existing workspace tokens).
- Web surfaces — this is native Qt only.

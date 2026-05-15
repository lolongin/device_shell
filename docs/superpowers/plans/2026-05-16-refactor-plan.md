# Device TUI 重构实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 7169 行的 `desktop_app.py` 拆分为职责单一的模块，理清设备对接层契约，同步搭建测试框架。

**Architecture:** 5 阶段增量重构：准备阶段（提取样式/工具/状态类）→ 设备层清理（Device extra 字段、repo_factory 分离）→ 小组件提取 → 主窗口 Mixin 拆分 → 测试搭建。每步可独立提交验证。

**Tech Stack:** Python 3.10+, PySide6, pytest, dataclasses

---

## 文件结构总图

重构后的 `src/` 结构（新建标记为 `+`）：

```
src/
  __init__.py              # (不改)
  desktop_app.py           # (精简 → 仅 import + main())
+ styles.py                # APP_STYLE + STATUS_COLORS 常量
  data.py                  # Device 模型 (加 extra 字段，剥离示例数据)
+ _sample_data.py          # sample_devices() + large_sample_devices()
  repository.py            # DeviceRepository Protocol + SampleDeviceRepository
  api_client.py            # DeviceApiClient Protocol + HttpDeviceApiClient
+ repo_factory.py          # create_repository_from_env()
+ helpers.py               # build_search_text(), mask_password(), status_color()
+ app_state.py             # RepositorySnapshot, DeviceTabState, SessionTabState
+ async_utils.py           # AsyncLoopThread
  session_protocol.py      # (不改)
  telnet_session.py        # (不改)
  linux_session.py         # (不改)
+ widgets/
    __init__.py
+   device_table.py        # CopyableDeviceTable, NoFocusItemDelegate
+   terminal_widget.py     # InteractiveTerminal, TerminalSyntaxHighlighter
+   command_record.py      # CommandRecordInput, CommandRecordResizeHandle
+   search_input.py        # SelectAllLineEdit
+ app/
    __init__.py
+   main_window.py         # DeviceDesktopApp (骨架 + 布局搭建)
+   session_ops.py         # SessionOpsMixin
+   occupancy_ops.py       # OccupancyOpsMixin
+   command_record_ops.py  # CommandRecordOpsMixin
+   desktop_state.py       # DesktopStateMixin
+   table_ops.py           # TableOpsMixin

tests/
+   conftest.py
+   test_helpers.py
+   test_app_state.py
+   test_repository.py
+   test_api_client.py
```

---

## Phase 1: 准备阶段

### Task 1.1: 创建目录结构并提取 styles.py

**Files:**
- Create: `src/styles.py`
- Create: `src/widgets/__init__.py`
- Create: `src/app/__init__.py`
- Modify: `src/desktop_app.py` (删除 APP_STYLE, 改为 import)

- [ ] **Step 1: 创建空包目录**

```bash
mkdir -p src/widgets src/app
touch src/widgets/__init__.py src/app/__init__.py
```

- [ ] **Step 2: 创建 styles.py**

内容：从 desktop_app.py 将 `APP_STYLE` 常量和 `STATUS_COLORS` 字典完整搬出。

```python
"""Application-wide style constants."""

from __future__ import annotations

from .data import STATUS_IDLE, STATUS_OCCUPIED, STATUS_PIPELINE, STATUS_OTHER

STATUS_COLORS = {
    STATUS_IDLE: "#3cc98e",
    STATUS_OCCUPIED: "#f5a623",
    STATUS_PIPELINE: "#5b6ef5",
    STATUS_OTHER: "#808080",
}

APP_STYLE = """
QWidget {
    background: #0b0f14;
    ... 完整样式表字符串（desktop_app.py 第 195-1700 行之间的 APP_STYLE 内容）...
}
"""
```

注意：需要验证 `APP_STYLE` 在 desktop_app.py 中的确切起止行号（从 `APP_STYLE = """` 到结尾的 `"""`）。确认后完整复制。

- [ ] **Step 3: 修改 desktop_app.py**

在 import 块增加：

```python
from .styles import APP_STYLE, STATUS_COLORS  # 替代原先的内联定义
```

删除 desktop_app.py 中 `APP_STYLE = """..."""` 和 `STATUS_COLORS = {...}` 的原始定义。

- [ ] **Step 4: 验证**

```bash
python -m py_compile src/styles.py src/desktop_app.py
python src/desktop_app.py  # 启动确认 GUI 正常
```

- [ ] **Step 5: 提交**

```bash
git add src/styles.py src/widgets/__init__.py src/app/__init__.py src/desktop_app.py
git commit -m "refactor: extract styles.py from desktop_app.py"
```

---

### Task 1.2: 提取 helpers.py

**Files:**
- Create: `src/helpers.py`
- Modify: `src/desktop_app.py` (删除 3 个函数，改为 import)

- [ ] **Step 1: 创建 helpers.py**

```python
"""Small utility functions shared across modules."""

from __future__ import annotations

from .data import Device


def build_search_text(device: Device) -> str:
    """Build a single searchable string from all device fields."""
    parts = [
        device.id, device.name, device.domain, device.device_type,
        device.cpu, device.status, device.owner or "", device.vendor,
        device.model, device.site, device.rack, device.version,
        device.notes, device.telnet_ip, device.ssh_ip,
        device.serial_ip,
    ]
    return " ".join(parts).lower()


def mask_password(password: str) -> str:
    """Mask a password for display."""
    return "******" if password else ""


def status_color(status: str) -> str:
    """Return a hex colour for the given device status."""
    mapping = {
        "空闲": "#3cc98e",
        "已被占用": "#f5a623",
        "流水线占用": "#5b6ef5",
    }
    return mapping.get(status, "#808080")
```

- [ ] **Step 2: 修改 desktop_app.py**

删除 `build_search_text`, `mask_password`, `status_color` 三个函数定义（约 1715-1743 行），在 import 块增加：

```python
from .helpers import build_search_text, mask_password, status_color
```

- [ ] **Step 3: 验证**

```bash
python -m py_compile src/helpers.py src/desktop_app.py
```

- [ ] **Step 4: 提交**

```bash
git add src/helpers.py src/desktop_app.py
git commit -m "refactor: extract helpers.py from desktop_app.py"
```

---

### Task 1.3: 提取 app_state.py

**Files:**
- Create: `src/app_state.py`
- Modify: `src/desktop_app.py` (删除 3 个 dataclass，改为 import)

- [ ] **Step 1: 创建 app_state.py**

```python
"""Shared state dataclasses for the desktop application."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PySide6.QtWidgets import QLabel, QSplitter, QTabWidget, QToolButton, QWidget

from .data import Device
from .telnet_session import HuaweiTelnetSession
from .linux_session import LinuxSshSession


@dataclass(slots=True)
class RepositorySnapshot:
    current_user: str
    devices: list[Device]
    owned_device_ids: set[str] | None


@dataclass(slots=True)
class DeviceTabState:
    device_id: str
    title: str
    page: QWidget
    session_tab_widget: QTabWidget
    session_splitter: QSplitter | None = None
    session_tab_widgets: list[QTabWidget] = field(default_factory=list)
    active_session_tab_widget: QTabWidget | None = None
    next_session_index: int = 1
    next_telnet_index: int = 1
    next_ssh_index: int = 1
    next_serial_index: int = 1
    tab_title_label: QLabel | None = None
    tab_header: QWidget | None = None
    tab_status_dot: QLabel | None = None
    tab_close_button: QToolButton | None = None


@dataclass(slots=True)
class SessionTabState:
    tab_id: str
    kind: str
    device_id: str
    title: str
    host: str
    port: int
    username: str
    password: str
    page: QWidget
    terminal: Any  # InteractiveTerminal (forward ref)
    session: HuaweiTelnetSession | LinuxSshSession
    log_path: Path
    log_at_line_start: bool = True
    log_input_buffer: str = ""
    log_pending_records: list[tuple[str, str, bool]] = field(default_factory=list)
    tab_title_label: QLabel | None = None
    tab_header: QWidget | None = None
    tab_status_dot: QLabel | None = None
    tab_close_button: QToolButton | None = None
    connecting: bool = False
    status_text: str = "Disconnected"
```

注意：`SessionTabState.terminal` 使用 `Any` 类型避免对 `InteractiveTerminal` 的前向引用循环。类型实际在运行时由 `desktop_app.py` 的导入解析。

- [ ] **Step 2: 修改 desktop_app.py**

删除 `RepositorySnapshot`, `DeviceTabState`, `SessionTabState` 三个类定义（约 1745-1793 行），在 import 块增加：

```python
from .app_state import RepositorySnapshot, DeviceTabState, SessionTabState
```

- [ ] **Step 3: 验证**

```bash
python -m py_compile src/app_state.py src/desktop_app.py
```

- [ ] **Step 4: 提交**

```bash
git add src/app_state.py src/desktop_app.py
git commit -m "refactor: extract app_state.py from desktop_app.py"
```

---

### Task 1.4: 提取 async_utils.py

**Files:**
- Create: `src/async_utils.py`
- Modify: `src/desktop_app.py` (删除 AsyncLoopThread，改为 import)

- [ ] **Step 1: 创建 async_utils.py**

```python
"""Async event-loop bridge for Qt applications."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Coroutine
from concurrent.futures import Future
from typing import Any


class AsyncLoopThread:
    """Dedicated thread running an asyncio event loop for background tasks."""

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def submit(self, coro: Coroutine[Any, Any, Any]) -> Future:
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    def cancel_pending(self, timeout: float = 2.0) -> None:
        for task in asyncio.all_tasks(self._loop):
            task.cancel()
        self._thread.join(timeout=timeout)

    def stop(self) -> None:
        self._loop.call_soon_threadsafe(self._loop.stop)
```

- [ ] **Step 2: 修改 desktop_app.py**

删除 `AsyncLoopThread` 类定义（约 1795-1831 行），在 import 块增加：

```python
from .async_utils import AsyncLoopThread
```

- [ ] **Step 3: 验证**

```bash
python -m py_compile src/async_utils.py src/desktop_app.py
```

- [ ] **Step 4: 提交**

```bash
git add src/async_utils.py src/desktop_app.py
git commit -m "refactor: extract async_utils.py from desktop_app.py"
```

---

## Phase 2: 设备层清理

### Task 2.1: Device 模型增加 extra 字段，剥离示例数据到 _sample_data.py

**Files:**
- Create: `src/_sample_data.py`
- Modify: `src/data.py` (增加 extra 字段; 删除示例数据函数)
- Modify: `src/repository.py` (导入路径改为 from ._sample_data)
- Modify: `src/desktop_app.py` (如导入 sample_devices，更新路径)

- [ ] **Step 1: data.py — 为 Device 增加 extra 字段**

```python
from dataclasses import dataclass, field
from typing import Any

@dataclass(slots=True)
class Device:
    # ... 现有字段不变 ...
    extra: dict[str, Any] = field(default_factory=dict)
```

注意：`slots=True` 的 dataclass 支持 `field(default_factory=...)`，因为 `dict` 是可变类型，放在 `field` 中是正确用法。

- [ ] **Step 2: 创建 _sample_data.py**

将 `data.py` 中的以下内容完整搬入：
- 常量 `CURRENT_USER`, `LOCAL_TEST_SSH_IP`, `LOCAL_TEST_SSH_USER`, `LOCAL_TEST_SSH_PASSWORD`, `MOCK_DEVICE_HOST`, `MOCK_DEVICE_TELNET_USER`, `MOCK_DEVICE_TELNET_PASSWORD`, `MOCK_LINUX_SSH_USER`, `MOCK_LINUX_SSH_PASSWORD`, `STATUS_OCCUPIED`, `STATUS_IDLE`, `STATUS_PIPELINE`, `STATUS_OTHER`
- 函数 `sample_devices()`
- 函数 `_with_board_ids()`
- 函数 `large_sample_devices()`

文件头：

```python
"""Sample device data for local GUI testing."""

from __future__ import annotations

from .data import Device, STATUS_IDLE, STATUS_OCCUPIED, STATUS_PIPELINE, STATUS_OTHER


CURRENT_USER = "li.wei"
LOCAL_TEST_SSH_IP = "192.168.1.15"
# ... 全部常量 ...
```

- [ ] **Step 3: 从 data.py 删除上述所有常量和函数**

data.py 只保留：
- `from __future__ import annotations`
- `from dataclasses import dataclass, field`
- `from typing import Any`
- `Device` dataclass 定义

文件结尾约 25 行，不再需要 400+ 行的示例数据。

- [ ] **Step 4: 更新 repository.py 的导入**

```python
from .data import Device
from ._sample_data import CURRENT_USER, sample_devices, large_sample_devices
from ._sample_data import STATUS_IDLE, STATUS_OCCUPIED, STATUS_PIPELINE, STATUS_OTHER
```

同时清理 `repository.py` 中不再通过 `data` 导入的状态常量。

- [ ] **Step 5: 检查 desktop_app.py 的导入**

确认 `desktop_app.py` 的 `from .data import` 只引用了 `STATUS_IDLE, STATUS_OCCUPIED, STATUS_OTHER, STATUS_PIPELINE, Device`，并且 `Device` 仍从 `data` 引用（正确）。如果还引用了 `CURRENT_USER` 等，改为 `from ._sample_data import CURRENT_USER`。

- [ ] **Step 6: 验证**

```bash
python -m py_compile src/data.py src/_sample_data.py src/repository.py src/desktop_app.py
python src/desktop_app.py  # 确认启动正常
```

- [ ] **Step 7: 提交**

```bash
git add src/data.py src/_sample_data.py src/repository.py src/desktop_app.py
git commit -m "refactor: add Device.extra field, split _sample_data.py from data.py"
```

---

### Task 2.2: 分离 repo_factory.py

**Files:**
- Create: `src/repo_factory.py`
- Modify: `src/repository.py` (删除 create_repository_from_env)

- [ ] **Step 1: 创建 repo_factory.py**

```python
"""Repository factory — selects implementation based on environment."""

from __future__ import annotations

import os

from .api_client import create_http_client_from_env
from .data import CURRENT_USER
from .repository import ApiDeviceRepository, DeviceRepository, SampleDeviceRepository


def create_repository_from_env() -> DeviceRepository:
    source = os.getenv("DEVICE_TUI_DATA_SOURCE", "sample").strip().lower()
    current_user = os.getenv("DEVICE_TUI_CURRENT_USER", CURRENT_USER)
    if source == "api":
        refresh_seconds = float(os.getenv("DEVICE_TUI_REFRESH_SECONDS", "30"))
        return ApiDeviceRepository(
            create_http_client_from_env(),
            refresh_interval_seconds=refresh_seconds,
        )
    try:
        sample_count = int(os.getenv("DEVICE_TUI_SAMPLE_DEVICE_COUNT", "0") or "0")
    except ValueError:
        sample_count = 0
    return SampleDeviceRepository(current_user=current_user, device_count=sample_count)
```

- [ ] **Step 2: 从 repository.py 删除 create_repository_from_env 函数**

- [ ] **Step 3: 更新 desktop_app.py 的导入**

将 `from .repository import ... create_repository_from_env` 改为：
```python
from .repo_factory import create_repository_from_env
```

- [ ] **Step 4: 验证**

```bash
python -m py_compile src/repo_factory.py src/repository.py src/desktop_app.py
```

- [ ] **Step 5: 提交**

```bash
git add src/repo_factory.py src/repository.py src/desktop_app.py
git commit -m "refactor: extract repo_factory.py from repository.py"
```

---

### Task 2.3: 清理 try/except 导入模式

**Files:**
- Modify: `src/repository.py`
- Modify: `src/api_client.py`
- Modify: `src/linux_session.py`
- Modify: `src/desktop_app.py`（保留其 try/except）

- [ ] **Step 1: repository.py — 清理 ImportError 处理**

替换整个 try/except 导入块为：

```python
from .api_client import (
    ApiClientError,
    ApiConflictError,
    DeviceApiClient,
    ApiNotFoundError,
)
from ._sample_data import (
    CURRENT_USER,
    STATUS_IDLE,
    STATUS_OCCUPIED,
    STATUS_OTHER,
    STATUS_PIPELINE,
)
from .data import Device
```

删除 `except ImportError:` 分支（约第 25-42 行）。

- [ ] **Step 2: api_client.py — 清理 ImportError 处理**

替换为：

```python
from .data import CURRENT_USER
```

- [ ] **Step 3: linux_session.py — 清理 ImportError 处理**

替换为：

```python
from .session_protocol import SessionCallbacks, SessionUnavailableError
```

- [ ] **Step 4: desktop_app.py — 保留 try/except 但精简**

保留 try/except 作为唯一入口文件的兼容机制，但可以用 clean import 替代：

```python
try:
    from .data import (
        STATUS_IDLE, STATUS_OCCUPIED, STATUS_OTHER, STATUS_PIPELINE, Device,
    )
    from .helpers import build_search_text, mask_password, status_color
    from .app_state import RepositorySnapshot, DeviceTabState, SessionTabState
    from .async_utils import AsyncLoopThread
    from .repo_factory import create_repository_from_env
    from .linux_session import LinuxSshSession
    from .repository import DeviceRepository, RepositoryConflictError, RepositoryError
    from .session_protocol import SessionCallbacks, SessionUnavailableError
    from .telnet_session import HuaweiTelnetSession, TelnetSessionError
# 备选：直接运行时使用绝对导入
except ImportError:
    from data import (
        STATUS_IDLE, STATUS_OCCUPIED, STATUS_OTHER, STATUS_PIPELINE, Device,
    )
    from helpers import build_search_text, mask_password, status_color
    # ... 其余同上 ...
```

- [ ] **Step 5: 验证**

```bash
python -m py_compile src/repository.py src/api_client.py src/linux_session.py src/desktop_app.py
```

- [ ] **Step 6: 提交**

```bash
git add src/repository.py src/api_client.py src/linux_session.py src/desktop_app.py
git commit -m "refactor: clean up try/except import patterns in non-entry modules"
```

---

## Phase 3: 小组件提取

### Task 3.1: 提取 widgets/device_table.py

**Files:**
- Create: `src/widgets/device_table.py`
- Modify: `src/desktop_app.py` (删除 NoFocusItemDelegate, CopyableDeviceTable 定义，改为 import)

- [ ] **Step 1: 创建 device_table.py**

```python
"""Device list table widget with copy support."""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QPainter
from PySide6.QtWidgets import (
    QApplication, QStyledItemDelegate, QStyleOptionViewItem,
    QTableWidget, QTableWidgetItem,
)


class NoFocusItemDelegate(QStyledItemDelegate):
    """Delegate that hides the dotted focus rectangle on table cells."""

    def paint(self, painter: Any, option: Any, index: Any) -> None:
        option.state &= ~QStyleOptionViewItem.State.HasFocus
        super().paint(painter, option, index)


class CopyableDeviceTable(QTableWidget):
    """A table widget that copies the selected cell value on Ctrl+C."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.setItemDelegate(NoFocusItemDelegate(self))

    def keyPressEvent(self, event: Any) -> None:
        if event.matches(QKeySequence.Copy):
            current = self.currentItem()
            if current is not None:
                text = current.text()
                if text:
                    QApplication.clipboard().setText(text)
                    return
        super().keyPressEvent(event)
```

- [ ] **Step 2: 修改 desktop_app.py**

删除 `NoFocusItemDelegate` 和 `CopyableDeviceTable` 的类定义（约 1833-1865 行），增加 import：

```python
from .widgets.device_table import CopyableDeviceTable
```

注意：`NoFocusItemDelegate` 只在 `CopyableDeviceTable` 内部使用，不需要单独导出。

- [ ] **Step 3: 验证**

```bash
python -m py_compile src/widgets/device_table.py src/desktop_app.py
```

- [ ] **Step 4: 提交**

```bash
git add src/widgets/device_table.py src/desktop_app.py
git commit -m "refactor: extract widgets/device_table.py from desktop_app.py"
```

---

### Task 3.2: 提取 widgets/search_input.py

**Files:**
- Create: `src/widgets/search_input.py`
- Modify: `src/desktop_app.py` (删除 SelectAllLineEdit 定义)

- [ ] **Step 1: 创建 search_input.py**

```python
"""Line edit that selects all text on double-click."""

from __future__ import annotations

from typing import Any

from PySide6.QtWidgets import QLineEdit


class SelectAllLineEdit(QLineEdit):
    """A QLineEdit that selects all text on double-click."""

    def mouseDoubleClickEvent(self, event: Any) -> None:
        self.selectAll()
        super().mouseDoubleClickEvent(event)
```

- [ ] **Step 2: 修改 desktop_app.py**

删除 `SelectAllLineEdit` 类定义（约 1867-1875 行），增加 import：

```python
from .widgets.search_input import SelectAllLineEdit
```

- [ ] **Step 3: 验证并提交**

---

### Task 3.3: 提取 widgets/terminal_widget.py

**Files:**
- Create: `src/widgets/terminal_widget.py`
- Modify: `src/desktop_app.py` (删除 InteractiveTerminal, TerminalSyntaxHighlighter 定义)

这是最大的提取任务（约 1160 行），必须确保边界精确。

- [ ] **Step 1: 确定提取边界**

将 desktop_app.py 中的以下类完整搬出（无任何逻辑修改）：
- `TerminalSyntaxHighlighter` (约 1877-2252 行)
- `InteractiveTerminal` (约 2254-3041 行)

同时搬出 `ANSI_ESCAPE_RE` 正则常量（约 185 行）。

- [ ] **Step 2: 创建 terminal_widget.py**

文件头：

```python
"""Terminal emulation widget with ANSI support and syntax highlighting."""

from __future__ import annotations

import re
from typing import Any, Callable

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import (
    QColor, QKeySequence, QSyntaxHighlighter, QTextBlockFormat,
    QTextCharFormat, QTextCursor, QTextOption, QBrush, QFont,
)
from PySide6.QtWidgets import QApplication, QPlainTextEdit, QToolTip

try:
    import pyte
except ModuleNotFoundError:
    pyte = None

from ..app_state import SessionTabState
from ..helpers import status_color


ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
```

然后将 `TerminalSyntaxHighlighter` 和 `InteractiveTerminal` 的完整类定义搬入。`InteractiveTerminal` 中引用 `ANSI_ESCAPE_RE` 的地方改为使用本模块的 `ANSI_ESCAPE_RE`。

注意：`InteractiveTerminal` 内部使用了 `mask_password` 和 `build_search_text`，需要在文件头引入：

```python
from ..helpers import mask_password
```

`InteractiveTerminal` 内部还使用了 `SessionTabState` 类型（例如 `_forward_text` 中的 `state: SessionTabState` 参数），已在头部导入。

- [ ] **Step 3: 修改 desktop_app.py**

删除以下内容：
- `ANSI_ESCAPE_RE` 常量定义（约 185 行）
- `TerminalSyntaxHighlighter` 整个类（约 1877-2252 行）
- `InteractiveTerminal` 整个类（约 2254-3041 行）

在 import 块增加：

```python
from .widgets.terminal_widget import InteractiveTerminal, TerminalSyntaxHighlighter, ANSI_ESCAPE_RE
```

- [ ] **Step 4: 检查 desktop_app.py 中对 InteractiveTerminal 的字符串引用**

在 desktop_app.py 中搜索 `"InteractiveTerminal"` — 如有前向引用字符串，确保与 import 的名称一致。

- [ ] **Step 5: 验证**

```bash
python -m py_compile src/widgets/terminal_widget.py src/desktop_app.py
python src/desktop_app.py  # 启动确认终端功能正常
```

- [ ] **Step 6: 提交**

```bash
git add src/widgets/terminal_widget.py src/desktop_app.py
git commit -m "refactor: extract widgets/terminal_widget.py from desktop_app.py"
```

---

### Task 3.4: 提取 widgets/command_record.py

**Files:**
- Create: `src/widgets/command_record.py`
- Modify: `src/desktop_app.py` (删除 CommandRecordInput, CommandRecordResizeHandle 定义)

- [ ] **Step 1: 创建 command_record.py**

```python
"""Command record input widget with resize handle."""

from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QPlainTextEdit, QSizePolicy, QWidget


class CommandRecordInput(QPlainTextEdit):
    """Multi-line input for recording device commands."""

    def __init__(self) -> None:
        super().__init__()
        self.setPlaceholderText("输入命令注记…")
        self.setTabChangesFocus(False)
        self.setAcceptDrops(False)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._submit_handler: Callable[[str], None] | None = None
        self._enter_sends = False

    def set_submit_handler(self, handler: Callable[[str], None]) -> None:
        self._submit_handler = handler

    def set_enter_sends(self, enter_sends: bool) -> None:
        self._enter_sends = enter_sends

    def current_command_line(self) -> str:
        return self.toPlainText().strip()

    def keyPressEvent(self, event: Any) -> None:
        if event.key() == Qt.Key_Return or event.key() == Qt.Key_Enter:
            if self._enter_sends:
                event.accept()
                if self._submit_handler:
                    self._submit_handler(self.toPlainText())
                return
            if event.modifiers() == Qt.ShiftModifier:
                event.accept()
                if self._submit_handler:
                    self._submit_handler(self.toPlainText())
                return
        super().keyPressEvent(event)


class CommandRecordResizeHandle(QFrame):
    """Draggable resize handle for the command record panel."""

    def __init__(self, resize_handler: Callable[[int], None], parent: QWidget) -> None:
        super().__init__(parent)
        self._resize_handler = resize_handler
        self._dragging = False
        self._start_y = 0
        self._start_height = 0
        self.setCursor(Qt.SizeVerCursor)
        self.setFixedHeight(6)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def mousePressEvent(self, event: Any) -> None:
        if event.button() == Qt.LeftButton:
            self._dragging = True
            self._start_y = self._event_global_y(event)
            self._start_height = self.parent().height()

    def mouseMoveEvent(self, event: Any) -> None:
        if self._dragging:
            delta = self._event_global_y(event) - self._start_y
            self._resize_handler(self._start_height - delta)

    def mouseReleaseEvent(self, event: Any) -> None:
        if event.button() == Qt.LeftButton:
            self._dragging = False

    @staticmethod
    def _event_global_y(event: Any) -> int:
        return event.globalPosition().toPoint().y() if hasattr(event, "globalPosition") else event.globalY()
```

- [ ] **Step 2: 修改 desktop_app.py**

删除 `CommandRecordInput` 和 `CommandRecordResizeHandle` 类定义（约 3043-3141 行），增加 import：

```python
from .widgets.command_record import CommandRecordInput, CommandRecordResizeHandle
```

- [ ] **Step 3: 验证并提交**

```bash
python -m py_compile src/widgets/command_record.py src/desktop_app.py
```

---

## Phase 4: 主窗口 Mixin 拆分

### Task 4.1: 创建 app/main_window.py（骨架）

**Files:**
- Create: `src/app/main_window.py`
- Modify: `src/desktop_app.py` (精简为 import + 入口)

核心思路：`DeviceDesktopApp` 作为多继承聚合类，每个 Mixin 负责一组相关方法。骨架仅保留 `__init__` 和布局搭建方法。

- [ ] **Step 1: 确定各 Mixin 的方法归属**

基于 desktop_app.py 的方法命名聚类（行号为近似值）：

| Mixin | 方法 | 约行数 |
|-------|------|--------|
| **主类骨架** | `__init__`, `_build_window`, `_build_layout`, `_build_toolbar`, `_build_left_panel`, `_build_activity_rail`, `_build_occupancy_panel`, `_build_device_context_panel`, `_build_center_panel`, `_build_right_panel`, `_new_table`, `_new_stat_chip`, `_new_terminal`, `_section_label`, `_build_command_record_panel`, helper 创建方法 | ~800 |
| **DesktopStateMixin** | `load_desktop_state`, `save_desktop_state`, `schedule_desktop_state_save`, `desktop_state_path`, `default_log_directory`, `default_command_record_groups`, 日志相关方法 | ~200 |
| **TableOpsMixin** | `apply_filters`, `refresh_device_table`, `refresh_owned_table`, `render_device_table_row`, `render_owned_table_row`, `enqueue_table_render_job`, `process_table_render_jobs`, `refresh_stats`, `refresh_domain_options`, `refresh_my_occupancy_filter_button`, 设备选取方法 | ~400 |
| **SessionOpsMixin** | `open_device_session`, `open_linux_session`, `open_serial_session`, `ensure_session_tab`, `ensure_device_tab`, `connect_session_tab`, `reconnect_session_tab`, `disconnect_session_tab`, `send_session_text`, `append_session_output`, `set_session_status`, 标签管理, 拖拽 | ~800 |
| **OccupancyOpsMixin** | `toggle_occupancy`, `power_off_device`, `handle_toggle_error`, 右键菜单中的占用操作 | ~80 |
| **CommandRecordOpsMixin** | `submit_command_record_input`, `add_command_record`, `rebuild_command_record_tabs`, `switch_command_group`, `add_command_group`, `rename_command_group`, `remove_command_group`, 各种命令记录方法 | ~250 |

- [ ] **Step 2: 创建 app/main_window.py**

```python
"""DeviceDesktopApp main window — skeleton combining all Mixins."""

from __future__ import annotations

import queue
import threading
from pathlib import Path
from typing import Any, Callable, Coroutine
from concurrent.futures import Future

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QApplication, QFrame, QGroupBox, QHBoxLayout, QLabel,
    QMainWindow, QPushButton, QScrollArea, QSplitter, QStatusBar,
    QTabWidget, QToolButton, QVBoxLayout, QWidget,
)

from ..app_state import DeviceTabState, SessionTabState
from ..async_utils import AsyncLoopThread
from ..data import Device
from ..repo_factory import create_repository_from_env
from ..repository import DeviceRepository
from ..styles import APP_STYLE

from .session_ops import SessionOpsMixin
from .occupancy_ops import OccupancyOpsMixin
from .command_record_ops import CommandRecordOpsMixin
from .desktop_state import DesktopStateMixin
from .table_ops import TableOpsMixin


class DeviceDesktopApp(
    SessionOpsMixin,
    OccupancyOpsMixin,
    CommandRecordOpsMixin,
    DesktopStateMixin,
    TableOpsMixin,
    QMainWindow,
):
    LOG_FLUSH_INTERVAL_MS = 250
    LOG_FLUSH_IMMEDIATE_CHARS = 65536
    COMMAND_RECORD_COLLAPSED_HEIGHT = 25
    COMMAND_RECORD_DEFAULT_HEIGHT = 148
    COMMAND_RECORD_MIN_HEIGHT = 116
    COMMAND_RECORD_MAX_HEIGHT = 600

    def __init__(self, repository: DeviceRepository | None = None) -> None:
        super().__init__()
        self.repository = repository or create_repository_from_env()
        self.async_loop = AsyncLoopThread()
        self.ui_queue: queue.SimpleQueue[tuple[Callable[..., None], tuple[object, ...]]] = queue.SimpleQueue()
        self.repository_lock = threading.Lock()
        self.search_index: dict[str, str] = {}
        self.device_by_id: dict[str, Device] = {}
        self.device_table_rows: dict[str, int] = {}
        self.owned_table_rows: dict[str, int] = {}
        self.devices: list[Device] = []
        self.visible_devices: list[Device] = []
        self.owned_visible_devices: list[Device] = []
        self.visible_status_counts: dict[str, int] = {}
        self.selected_device_id = ""
        self.current_user = ""
        self.owned_device_ids: set[str] | None = None
        self.refresh_generation = 0
        self.closed = False
        self.loading_snapshot = False
        self.my_occupancy_filter_enabled = False
        self.recent_device_ids: list[str] = []
        self.command_record_groups: list[dict[str, object]] = [
            {"name": "终端", "content": ""},
        ]
        self.current_command_group = 0
        self.command_record_collapsed = True
        self.command_enter_sends = False
        self.command_record_height = self.COMMAND_RECORD_DEFAULT_HEIGHT
        self.connection_params_collapsed = True
        self.left_sidebar_collapsed = False
        self.left_sidebar_animation = None
        self.command_tab_buttons: list[QToolButton] = []
        self.command_tab_close_buttons: list[QToolButton] = []
        self.state_path = self.desktop_state_path()
        self.log_directory = self.default_log_directory()
        self.device_tabs_by_id: dict[str, DeviceTabState] = {}
        self.session_tabs_by_id: dict[str, SessionTabState] = {}
        self.pending_futures: set[Future] = set()
        self._drag_session_tab_id = ""
        self._last_desktop_state_payload = ""
        self._last_device_table_signature: tuple[object, ...] = ()
        self._last_owned_table_signature: tuple[object, ...] = ()
        self._table_render_jobs: list[dict[str, object]] = []
        self._table_render_generation = 0
        self.next_session_sequence = 1

        self.refresh_timer = QTimer(self)
        self.refresh_timer.setSingleShot(True)
        self.refresh_timer.timeout.connect(self.refresh_snapshot)
        self.filter_timer = QTimer(self)
        self.filter_timer.setSingleShot(True)
        self.filter_timer.setInterval(120)
        self.filter_timer.timeout.connect(self.apply_filters)
        self.state_save_timer = QTimer(self)
        self.state_save_timer.setSingleShot(True)
        self.state_save_timer.timeout.connect(self.save_desktop_state)
        self.ui_timer = QTimer(self)
        self.ui_timer.setInterval(10)
        self.ui_timer.timeout.connect(self._drain_ui_queue)
        self.log_flush_timer = QTimer(self)
        self.log_flush_timer.setSingleShot(True)
        self.log_flush_timer.timeout.connect(self.flush_pending_session_logs)
        self.table_render_timer = QTimer(self)
        self.table_render_timer.setSingleShot(True)
        self.table_render_timer.timeout.connect(self.process_table_render_jobs)

        self.load_desktop_state()
        self._build_window()
        self._build_layout()
        self._wire_events()
        self.update_controls()
        self.ui_timer.start()
        self.refresh_snapshot()

    # ======== 布局搭建方法（留在骨架中） ========
    # 以下方法全部从原 desktop_app.py 完整搬入，不做修改：
    # _build_window(), _build_layout(), _build_toolbar(),
    # _build_left_panel(), _build_activity_rail(),
    # _new_activity_button(), _activity_icon(),
    # _build_occupancy_panel(), _build_device_context_panel(),
    # _quick_action_icon(), _configure_quick_action_button(),
    # _build_center_panel(), _build_right_panel(),
    # _build_command_record_panel(),
    # _section_label(), _new_table(), _new_stat_chip(), _new_terminal(),
    # sync_left_search(), schedule_apply_filters(), clear_filters(),
    # set_my_occupancy_filter(),
    # apply_left_sidebar_state(), animate_left_sidebar_state(),
    # toggle_left_sidebar(), toggle_connection_params(),
    # toggle_command_record_panel(), resize_command_record_panel(),
    # clamp_command_record_height(),
    # dispatch_ui(), _drain_ui_queue(), run_blocking(), run_coro(),
    # cancel_pending_futures(),
    # _wire_events(), eventFilter(),
    # start_session_tab_drag(), handle_session_tab_drop(),
    # split_direction_for_drop(), split_session(), split_session_to_right(),
    # set_status_message(), handle_background_error(),
    # show_warning(), show_error(), closeEvent(),
    # refresh_current_operation_label(),
    # update_controls(),
    # refresh_filter_summary(), filter_chip_html(),
    # get_device_by_id(), ensure_valid_selection(),
    # select_device_in_table(), _select_device_row(),
    # get_selected_device(), get_quick_action_device(),
    # _device_id_from_table(), _device_from_table(),
    # copy_text_to_clipboard(), device_row_copy_text(),
    # device_connection_copy_text(), copy_device_field(),
    # device_ssh_username(), device_ssh_password(),
    # device_serial_username(), device_serial_password(),
    # can_view_serial_connection(), copy_selected_device_field(),
    # copy_selected_table_row(), _mark_recent_device(),
    # handle_device_table_selected(), handle_owned_table_selected(),
    # activate_device(), locate_device_in_list(),
    # show_device_table_context_menu(), show_terminal_context_menu(),
    # show_device_quick_context_menu(), show_session_quick_context_menu(),
    # _add_session_split_actions(), _handle_session_split_action(),
    # event_has_session_tab(),
    # text_matches_keyword(), device_search_text(),
    # device_matches_hidden_keyword(),
    # clone_telnet_session(), clone_ssh_session(), clone_serial_session(),
    # sync_auth_fields_from_selected(), refresh_device_context(),
    # refresh_workspace_context(), refresh_session_jump_combo(),
    # ordered_session_states(), session_jump_text(),
    # session_kind_label(), session_display_title(),
    # session_status_label(), handle_session_jump_activated(),
    # jump_to_session(), handle_session_tab_changed(),
    # handle_split_session_tab_changed(),
    # handle_split_session_tab_clicked(),
    # update_center_stage_state(), current_session_key(),
    # current_device_tab_state(), current_session_state(),
    # _device_tab_for_page(), _session_state_for_page(),
    # _session_states_for_device(),
    # session_tab_widgets_for_device(),
    # active_session_tabs_for_device(),
    # find_session_tab_widget(), mark_active_session_tab_widget(),
    # is_my_occupied_device(), can_power_off_device(),
    # reconnect_current_session(), disconnect_current_session(),
    # open_current_session_log(),
    # refresh_command_tab_styles(), toggle_command_enter_mode(),
    # update_command_enter_mode(), apply_connection_params_state(),
    # apply_command_record_panel_state(),
    # cancel_table_render_jobs(),
    # _set_table_item(), my_occupancy_count(),
    # stat_chip_html(),
```

这是一个非常大的文件，但它是方法的"收集器"。全部方法从原 desktop_app.py 搬入，不做逻辑修改。

- [ ] **Step 2: 验证**

```bash
python -m py_compile src/app/main_window.py
```

- [ ] **Step 3: 精简 desktop_app.py**

最终 desktop_app.py 只保留：

```python
"""Device TUI desktop application entry point."""
from __future__ import annotations

import sys

try:
    from PySide6.QtWidgets import QApplication
except ModuleNotFoundError:
    QApplication = None  # type: ignore[assignment]
    PYSIDE6_IMPORT_ERROR = __import__("sys").exc_info()[1]
else:
    PYSIDE6_IMPORT_ERROR = None

from src.app.main_window import DeviceDesktopApp


def main() -> None:
    if PYSIDE6_IMPORT_ERROR is not None:
        raise SystemExit(
            "PySide6 is not installed. Run `pip install -e .` or `pip install PySide6` and try again."
        )
    app = QApplication.instance() or QApplication([])
    window = DeviceDesktopApp()
    window.show()
    raise SystemExit(app.exec())


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 提交**

```bash
git add src/app/main_window.py src/desktop_app.py
git commit -m "refactor: create main_window.py skeleton, leave entry point in desktop_app.py"
```

---

### Task 4.2: 创建 app/session_ops.py

**Files:**
- Create: `src/app/session_ops.py`
- Modify: `src/app/main_window.py` (导入 SessionOpsMixin)

- [ ] **Step 1: 创建 session_ops.py**

```python
"""Session management mixin for DeviceDesktopApp."""

from __future__ import annotations

from typing import Any

from ..data import Device
from ..telnet_session import HuaweiTelnetSession, TelnetSessionError
from ..linux_session import LinuxSshSession, SessionUnavailableError
from ..widgets.terminal_widget import InteractiveTerminal
from ..app_state import DeviceTabState, SessionTabState


class SessionOpsMixin:
    """Mixin providing session connection, tab management, and terminal operations.

    Must be used with DeviceDesktopApp (provides self.repository, self.async_loop,
    self.device_tabs_by_id, self.session_tabs_by_id, etc.).
    """

    # === 会话打开 ===
    def open_device_session(self, device: Device | None = None) -> None:
        """Open a Telnet session for the given device (or selected device)."""
        ...  # 完整实现从原 desktop_app.py 搬入

    def open_linux_session(self, device: Device | None = None) -> None:
        """Open an SSH session for the given device."""
        ...

    def open_serial_session(self, device: Device | None = None) -> None:
        """Open a serial session for the given device."""
        ...

    # === Tab 管理 ===
    def ensure_session_tab(self, ...) -> SessionTabState:
        ...

    def ensure_device_tab(self, device: Device) -> DeviceTabState:
        ...

    def create_session_tab_widget(self, device_id: str, parent: QWidget) -> QTabWidget:
        ...

    def next_session_title(self, device_tab: DeviceTabState, kind: str) -> str:
        ...

    def next_session_tab_id(self, device_id: str, kind: str) -> str:
        ...

    # === 连接/断开/重连 ===
    def connect_session_tab(self, tab_id: str) -> None:
        ...

    def disconnect_session_tab(self, tab_id: str) -> None:
        ...

    def reconnect_session_tab(self, tab_id: str) -> None:
        ...

    def send_session_text(self, tab_id: str, text: str) -> None:
        ...

    def resize_session_pty(self, tab_id: str, columns: int, lines: int) -> None:
        ...

    def set_session_status(self, tab_id: str, status: str) -> None:
        ...

    def append_session_output(self, tab_id: str, message: str) -> None:
        ...

    # === 关闭 ===
    def close_session_tab_for_page(self, page: QWidget) -> None:
        ...

    def close_child_session_tab_at_index(self, ...) -> None:
        ...

    def close_session_tab_at_index(self, index: int) -> None:
        ...

    def close_device_tab_for_page(self, page: QWidget) -> None:
        ...

    def close_device_tab_at_index(self, index: int) -> None:
        ...

    def close_device_tab_state(self, device_tab: DeviceTabState) -> None:
        ...

    def normalize_session_splitters(self, device_tab: DeviceTabState) -> None:
        ...

    # === 标签头样式 ===
    def _install_device_tab_header(self, ...) -> None:
        ...

    def _install_session_tab_header(self, ...) -> None:
        ...

    def _install_tab_header(self, ...) -> None:
        ...

    def _tab_connection_state(self, state: SessionTabState) -> str:
        ...

    def refresh_session_header(self, state: SessionTabState) -> None:
        ...

    def _device_connection_state(self, state: DeviceTabState) -> str:
        ...

    def _apply_tab_header_style(self, ...) -> None:
        ...

    def _refresh_tab_header_styles(self) -> None:
        ...

    # === 会话标签菜单 ===
    def _add_session_log_actions(self, menu, state, tab_id) -> dict:
        ...

    def _handle_session_log_action(self, ...) -> None:
        ...

    def _handle_device_quick_action(self, ...) -> None:
        ...
```

实际实现时：将原 desktop_app.py 中所有属于会话管理的方法完整复制至此文件，方法体不做修改。

- [ ] **Step 2: 在 main_window.py 导入**

```python
from .session_ops import SessionOpsMixin
```

`DeviceDesktopApp` 类已继承 `SessionOpsMixin`。

- [ ] **Step 3: 验证**

```bash
python -m py_compile src/app/session_ops.py src/app/main_window.py
```

- [ ] **Step 4: 提交**

---

### Task 4.3: 创建 app/occupancy_ops.py

**Files:**
- Create: `src/app/occupancy_ops.py`

- [ ] **Step 1: 创建 occupancy_ops.py**

```python
"""Occupancy management mixin for DeviceDesktopApp."""

from __future__ import annotations

from typing import Any

from ..data import Device
from ..repository import RepositoryConflictError


class OccupancyOpsMixin:
    """Mixin providing occupancy toggle and power-off operations."""

    def toggle_occupancy(self, device: Device | None = None) -> None:
        ...

    def power_off_selected_device(self) -> None:
        ...

    def power_off_device(self, device: Device) -> None:
        ...

    def handle_toggle_error(self, exc: Exception) -> None:
        ...
```

方法体从原 desktop_app.py 完整复制。

- [ ] **Step 2: 在 main_window.py 导入**

```python
from .occupancy_ops import OccupancyOpsMixin
```

- [ ] **Step 3: 验证并提交**

---

### Task 4.4: 创建 app/command_record_ops.py

**Files:**
- Create: `src/app/command_record_ops.py`

方法列表：
- `submit_command_record_input`
- `submit_current_command_record`
- `send_command_text_to_current_session`
- `broadcast_command_record_input`
- `command_record_payload`
- `add_command_record`
- `current_command_group_index`
- `current_command_records`
- `rebuild_command_record_tabs`
- `switch_command_group`
- `add_command_group`
- `rename_command_group`
- `show_command_group_context_menu`
- `remove_command_group`
- `_save_current_command_content`
- `_load_current_command_content`
- `clear_current_command_record`
- `apply_command_record_panel_state`
- `refresh_command_tab_styles`

与 Task 4.2 和 4.3 相同的模式：创建 Mixin 类，搬入方法。

---

### Task 4.5: 创建 app/desktop_state.py

**Files:**
- Create: `src/app/desktop_state.py`

方法列表：
- `desktop_state_path`
- `default_log_directory`
- `default_command_record_groups`
- `load_desktop_state`
- `schedule_desktop_state_save`
- `save_desktop_state`
- `session_log_path`
- `unique_log_path`
- `safe_log_component`
- `write_session_log_line`
- `write_session_log`
- `schedule_session_log_flush`
- `flush_pending_session_logs`
- `flush_session_log_state`
- `finish_session_log_record`
- `sanitize_log_text`
- `log_timestamp`
- `log_session_input`
- `skip_escape_sequence`
- `flush_session_input_log`
- `open_session_log`
- `open_session_log_directory`
- `open_local_path`
- `change_log_directory`
- `move_active_session_logs`

---

### Task 4.6: 创建 app/table_ops.py

**Files:**
- Create: `src/app/table_ops.py`

方法列表：
- `refresh_snapshot`
- `schedule_next_refresh`
- `refresh_domain_options`
- `apply_filters`
- `refresh_stats`
- `stat_chip_html`
- `refresh_my_occupancy_filter_button`
- `my_occupancy_count`
- `is_my_occupied_device`
- `can_power_off_device`
- `cancel_table_render_jobs`
- `enqueue_table_render_job`
- `process_table_render_jobs`
- `render_table_job_rows`
- `render_device_table_row`
- `render_owned_table_row`
- `refresh_device_table`
- `refresh_owned_table`
- `_set_table_item`
- `text_matches_keyword`
- `device_search_text`
- `device_matches_hidden_keyword`
- 以及设备选取辅助方法

---

### Task 4.7: 整合验证

- [ ] **Step 1: 确保 desktop_app.py 可以正常运行**

```bash
python src/desktop_app.py
```

测试核心功能：
1. 启动 GUI，确认布局正常
2. 设备列表显示和筛选
3. 打开一个 Telnet 会话
4. 打开一个 SSH 会话
5. 占用/释放操作
6. 命令记录面板
7. 关闭程序

- [ ] **Step 2: 提交整个 Phase 4**

```bash
git add src/app/
git commit -m "refactor: split DeviceDesktopApp into mixin modules"
```

---

## Phase 5: 测试搭建

### Task 5.1: 配置 pytest

**Files:**
- Create: `tests/__init__.py` (空)
- Create: `tests/conftest.py`
- Modify: `pyproject.toml` (添加 pytest 配置)

- [ ] **Step 1: 创建 pytest 配置**

pyproject.toml 追加：

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
pythonpath = ["src"]
```

- [ ] **Step 2: 创建 tests/conftest.py**

```python
"""Shared fixtures for testing."""

from __future__ import annotations

import pytest

from src.data import Device
from src.repository import SampleDeviceRepository


@pytest.fixture
def sample_repo() -> SampleDeviceRepository:
    return SampleDeviceRepository()


@pytest.fixture
def sample_device() -> Device:
    return Device(
        id="TEST-001",
        name="Test-Device",
        domain="测试",
        device_type="Router",
        cpu="ARM-1",
        status="空闲",
        owner=None,
        ssh_ip="10.0.0.1",
        telnet_ip="10.0.0.1",
        username="admin",
        password="secret",
        vendor="TestCorp",
        model="T-1000",
        site="TestLab",
        rack="R01-U01",
        version="v1.0",
        notes="Test device",
    )
```

- [ ] **Step 3: 验证**

```bash
pip install pytest
pytest --version
pytest tests/ -v  # 尚无测试，应提示 "no tests ran"
```

- [ ] **Step 4: 提交**

```bash
git add tests/ pyproject.toml
git commit -m "test: configure pytest"
```

---

### Task 5.2: 测试 helpers.py

**Files:**
- Create: `tests/test_helpers.py`

- [ ] **Step 1: 编写测试**

```python
"""Tests for helpers module."""

from __future__ import annotations

from src.data import Device
from src.helpers import build_search_text, mask_password, status_color


class TestBuildSearchText:
    def test_joins_all_device_fields(self, sample_device: Device) -> None:
        result = build_search_text(sample_device)
        assert "TEST-001" in result
        assert "Test-Device" in result
        assert "Router" in result

    def test_lowercase(self, sample_device: Device) -> None:
        result = build_search_text(sample_device)
        assert result == result.lower()

    def test_empty_owner_does_not_crash(self) -> None:
        d = Device(
            id="X", name="x", domain="x", device_type="x",
            cpu="x", status="x", owner=None,
            ssh_ip="", telnet_ip="", username="", password="",
            vendor="", model="", site="", rack="", version="", notes="",
        )
        build_search_text(d)  # should not raise


class TestMaskPassword:
    def test_returns_asterisks_for_non_empty(self) -> None:
        assert mask_password("secret123") == "******"

    def test_returns_empty_for_empty(self) -> None:
        assert mask_password("") == ""


class TestStatusColor:
    def test_known_status(self) -> None:
        assert status_color("空闲") == "#3cc98e"

    def test_unknown_status_returns_gray(self) -> None:
        assert status_color("未知") == "#808080"
```

- [ ] **Step 2: 运行并验证**

```bash
pytest tests/test_helpers.py -v
```

- [ ] **Step 3: 提交**

```bash
git add tests/test_helpers.py
git commit -m "test: add helpers unit tests"
```

---

### Task 5.3: 测试 app_state.py

**Files:**
- Create: `tests/test_app_state.py`

- [ ] **Step 1: 编写测试**

```python
"""Tests for app_state module."""

from __future__ import annotations

from src.app_state import RepositorySnapshot


class TestRepositorySnapshot:
    def test_create_snapshot(self, sample_device) -> None:
        snapshot = RepositorySnapshot(
            current_user="test.user",
            devices=[sample_device],
            owned_device_ids={"TEST-001"},
        )
        assert snapshot.current_user == "test.user"
        assert len(snapshot.devices) == 1
        assert "TEST-001" in snapshot.owned_device_ids
```

- [ ] **Step 2: 运行并提交**

---

### Task 5.4: 测试 repository 层

**Files:**
- Create: `tests/test_repository.py`

- [ ] **Step 1: 编写测试**

```python
"""Tests for repository module."""

from __future__ import annotations

import pytest

from src.data import Device, STATUS_IDLE, STATUS_OCCUPIED
from src.repository import (
    SampleDeviceRepository, RepositoryConflictError, RepositoryError,
)


class TestSampleDeviceRepository:
    def test_fetch_devices_returns_copies(self, sample_repo: SampleDeviceRepository) -> None:
        devices = sample_repo.fetch_devices()
        devices[0].name = "Hacked"
        refetched = sample_repo.fetch_devices()
        assert refetched[0].name != "Hacked"

    def test_fetch_owned_device_ids(self, sample_repo: SampleDeviceRepository) -> None:
        ids = sample_repo.fetch_owned_device_ids()
        assert isinstance(ids, set)

    def test_claim_device(self, sample_repo: SampleDeviceRepository) -> None:
        # Find an idle device
        idle = next(d for d in sample_repo.fetch_devices() if d.status == STATUS_IDLE)
        result = sample_repo.claim_device(idle.id, "test.user")
        assert "Claimed" in result

    def test_claim_already_owned_raises(self, sample_repo: SampleDeviceRepository) -> None:
        occupied = next(d for d in sample_repo.fetch_devices() if d.status == STATUS_OCCUPIED)
        with pytest.raises(RepositoryConflictError):
            sample_repo.claim_device(occupied.id, "test.user")

    def test_release_not_owned_raises(self, sample_repo: SampleDeviceRepository) -> None:
        idle = next(d for d in sample_repo.fetch_devices() if d.status == STATUS_IDLE)
        with pytest.raises(RepositoryConflictError):
            sample_repo.release_device(idle.id, "test.user")

    def test_toggle_claim_release(self, sample_repo: SampleDeviceRepository) -> None:
        idle = next(d for d in sample_repo.fetch_devices() if d.status == STATUS_IDLE)
        sample_repo.toggle_device(idle.id, "test.user")
        sample_repo.toggle_device(idle.id, "test.user")
        # Should be back to idle via release
        refreshed = sample_repo.fetch_devices()
        match = next(d for d in refreshed if d.id == idle.id)
        assert match.status == STATUS_IDLE

    def test_power_off_unsupported_raises(self, sample_repo: SampleDeviceRepository) -> None:
        device = next(d for d in sample_repo.fetch_devices() if not d.supports_power_off)
        if device.owner:
            sample_repo.release_device(device.id, device.owner)
        with pytest.raises(RepositoryConflictError):
            sample_repo.power_off_device(device.id, "test.user")

    def test_find_unknown_device_raises(self, sample_repo: SampleDeviceRepository) -> None:
        with pytest.raises(RepositoryError, match="Unknown device id"):
            sample_repo.claim_device("NONEXISTENT", "user")
```

- [ ] **Step 2: 运行并提交**

```bash
pytest tests/test_repository.py -v
git add tests/test_repository.py
git commit -m "test: add repository unit tests"
```

---

### Task 5.5: 测试 api_client.py

**Files:**
- Create: `tests/test_api_client.py`

- [ ] **Step 1: 编写基本测试**

```python
"""Tests for api_client module."""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from urllib.parse import urlparse

import pytest

from src.api_client import (
    ApiClientError, ApiConflictError, ApiNotFoundError,
    HttpDeviceApiClient,
)


# 简易 HTTP 测试服务器
class _MockHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/me":
            self._json({"current_user": "test.user"})
        elif path == "/api/devices":
            self._json({"revision": 1, "devices": [
                {"device_id": "D1", "display_name": "Device 1"},
            ]})
        elif "/api/events" in path:
            self._json({"revision": 1, "changed": False})
        else:
            self.send_response(404)
            self.end_headers()

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if "/toggle" in path:
            self._json({"message": "Toggled D1"})
        elif "/claim" in path:
            self._json({"message": "Claimed D1"})
        elif "/release" in path:
            self._json({"message": "Released D1"})
        elif "/power-off" in path:
            self._json({"message": "Powered off D1"})
        else:
            self.send_response(404)
            self.end_headers()

    def _json(self, data: dict) -> None:
        body = json.dumps(data).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args: Any) -> None:
        pass  # suppress server logs


@pytest.fixture(scope="module")
def mock_server():
    server = HTTPServer(("127.0.0.1", 0), _MockHandler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()


class TestHttpDeviceApiClient:
    def test_get_current_user(self, mock_server):
        port = mock_server.server_port
        client = HttpDeviceApiClient(f"http://127.0.0.1:{port}")
        assert client.get_current_user() == "test.user"

    def test_list_devices(self, mock_server):
        port = mock_server.server_port
        client = HttpDeviceApiClient(f"http://127.0.0.1:{port}")
        devices = client.list_devices()
        assert len(devices) == 1
        assert devices[0]["device_id"] == "D1"

    def test_toggle_device(self, mock_server):
        port = mock_server.server_port
        client = HttpDeviceApiClient(f"http://127.0.0.1:{port}")
        result = client.toggle_device("D1", "test.user")
        assert "Toggled" in result.get("message", "")

    def test_wait_for_update_no_change(self, mock_server):
        port = mock_server.server_port
        client = HttpDeviceApiClient(f"http://127.0.0.1:{port}")
        result = client.wait_for_update(1, 1.0)
        assert result is None
```

- [ ] **Step 2: 运行并提交**

```bash
pytest tests/test_api_client.py -v
git add tests/test_api_client.py
git commit -m "test: add API client unit tests"
```

---

## 自审清单

- [ ] **Spec 覆盖**: 每项 spec 需求都能找到对应任务。Device extra 字段 → Task 2.1, 设备层契约 → Phase 2, UI 拆分 → Phase 3+4, 测试 → Phase 5。
- [ ] **无占位符**: 所有 code block 包含完整可执行的代码（上述 plan 中的code为示例，实际执行时需复制原 desktop_app.py 的确切方法体）。
- [ ] **类型一致性**: Mixin 名称、导入路径、方法签名在 task 间保持一致。
- [ ] **可逆性**: 每步可独立提交，git revert 某一步不会影响其他步骤。

---

## 执行方式选择

计划完成，保存在 `docs/superpowers/plans/2026-05-16-refactor-plan.md`。

**两种执行方式：**

1. **Subagent-Driven（推荐）** — 为每个 task 派发独立 subagent，task 间做 review 和验证，快速迭代
2. **Inline Execution** — 在当前会话中逐步执行，每步手动验证

你倾向哪种？

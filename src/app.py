from __future__ import annotations

import asyncio
import shutil
import subprocess
import time
from collections.abc import Coroutine

from rich.cells import cell_len, set_cell_size
from rich.text import Text
from textual import events, on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.css.query import NoMatches
from textual.reactive import reactive
from textual.suggester import SuggestFromList
from textual.widgets import Button, Footer, Header, Input, Label, ListItem, ListView, RichLog, Static

try:
    from .data import (
        STATUS_IDLE,
        STATUS_OCCUPIED,
        STATUS_OTHER,
        STATUS_PIPELINE,
        Device,
    )
    from .repository import (
        DeviceRepository,
        RepositoryConflictError,
        RepositoryError,
        create_repository_from_env,
    )
    from .linux_session import LinuxSshSession
    from .session_protocol import SessionCallbacks, SessionUnavailableError
    from .telnet_session import HuaweiTelnetSession, TelnetSessionError
    from .workflow_runner import WorkflowContext, WorkflowExecutionError, WorkflowRunner
    from .workflows import WorkflowParseError, parse_workflow_input
except ImportError:
    from data import (
        STATUS_IDLE,
        STATUS_OCCUPIED,
        STATUS_OTHER,
        STATUS_PIPELINE,
        Device,
    )
    from repository import (
        DeviceRepository,
        RepositoryConflictError,
        RepositoryError,
        create_repository_from_env,
    )
    from linux_session import LinuxSshSession
    from session_protocol import SessionCallbacks, SessionUnavailableError
    from telnet_session import HuaweiTelnetSession, TelnetSessionError
    from workflow_runner import WorkflowContext, WorkflowExecutionError, WorkflowRunner
    from workflows import WorkflowParseError, parse_workflow_input


ALL_STATUS = "\u5168\u90e8\u72b6\u6001"
STATUS_ORDER = [STATUS_OCCUPIED, STATUS_IDLE, STATUS_PIPELINE, STATUS_OTHER]
WORKFLOW_COMMANDS = [
    "/collect_log",
    "/change_cc <value>",
]


APP_CSS = """
Screen {
    background: #08111f;
    color: #e8f0ff;
}

#shell {
    layout: horizontal;
    height: 1fr;
    padding: 1 2;
}

#left-pane {
    width: 2fr;
    margin-right: 1;
}

#right-pane {
    width: 1fr;
    layout: vertical;
}

.panel {
    border: tall #24415f;
    background: #0d1726;
    padding: 1;
}

#detail-panel {
    height: 1fr;
    min-height: 1;
}

#cli-panel {
    layout: vertical;
    height: 5fr;
    min-height: 8;
    margin-top: 1;
}

#device-panel {
    height: 3fr;
    min-height: 16;
}

#occupancy-panel {
    height: 2fr;
    min-height: 11;
    margin-top: 1;
}

#occupancy-meta {
    margin-bottom: 0;
}

.panel-title {
    color: #8ac6ff;
    text-style: bold;
    margin-bottom: 0;
}

.section-copy {
    color: #7d93ad;
    margin-bottom: 1;
}

#toolbar-row {
    height: auto;
    margin-bottom: 1;
}

#toolbar-row #filter-input {
    width: 1fr;
    margin-bottom: 0;
    margin-right: 1;
}

#stats-strip {
    width: auto;
    color: #9cb4ce;
    background: #091422;
    border: round #16314d;
    padding: 0 1;
}

#filter-input {
    background: #08111f;
    color: #e8f0ff;
    border: round #16314d;
}

#filter-input:focus {
    border: round #5db4ff;
}

#filter-row {
    height: auto;
    margin-bottom: 1;
}

#status-row {
    height: auto;
    align: left middle;
    margin-bottom: 1;
}

#keyword-row {
    height: auto;
    align: left middle;
}

.keyword-filter {
    width: 1fr;
    margin-right: 1;
    border: round #16314d;
    background: #08111f;
    color: #e8f0ff;
}

.keyword-filter:focus {
    border: round #5db4ff;
}

#cpu-filter-input {
    margin-right: 0;
}

.list-header {
    color: #7d93ad;
    background: #091422;
    border-bottom: solid #16314d;
    padding: 0 1;
    margin-bottom: 0;
    height: 1;
}

.chip-section {
    width: auto;
    height: auto;
    margin-right: 2;
    align: left middle;
}

.chip-group-title {
    width: auto;
    min-width: 5;
    color: #7d93ad;
    padding: 0 1 0 0;
}

.filter-chip {
    width: auto;
    min-width: 8;
    margin-right: 0;
    background: transparent;
    color: #b8c9dd;
    border: round #1d3550;
}

.filter-chip:hover {
    background: transparent;
    border: round #355f8c;
}

.filter-chip.-active {
    background: transparent;
    color: #ffffff;
    border: round #5db4ff;
    text-style: bold;
}

.filter-chip:focus {
    background: transparent;
    color: #ffffff;
    border: round #8ac6ff;
}

ListView {
    scrollbar-background: #0d1726;
    scrollbar-color: #5db4ff;
    scrollbar-color-hover: #8ac6ff;
    background: #08111f;
    border: none;
    height: 1fr;
}

ListView:focus {
    border: none;
}

ListItem {
    padding: 0 1;
    margin: 0;
    background: transparent;
    color: #d9e8ff;
    height: 1;
    border-left: blank #08111f;
}

ListItem.--highlight {
    background: #0f2238;
    border-left: solid #5db4ff;
    color: #ffffff;
    text-style: bold;
}

#detail-card {
    border: round #2a4f75;
    background: #0a1422;
    padding: 1 2;
    height: 1fr;
}

.cli-switch-row {
    height: auto;
    margin-top: 0;
    margin-bottom: 0;
}

.cli-switch-button {
    width: 1fr;
    margin-right: 1;
    background: transparent;
    color: #b8c9dd;
    border: round #1d3550;
}

.cli-switch-button.-last {
    margin-right: 0;
}

.cli-switch-button:hover {
    background: transparent;
    border: round #355f8c;
}

.cli-switch-button.-active {
    background: transparent;
    color: #ffffff;
    border: round #5db4ff;
    text-style: bold;
}

.cli-auth-block {
    background: transparent;
    border: none;
    padding: 0;
    margin-bottom: 1;
}

#cli-auth-stack {
    height: auto;
    margin-bottom: 0;
}

#device-auth-block,
#linux-auth-block {
    height: auto;
}

#cli-command-meta {
    height: 1;
    color: #88a0ba;
    margin-top: 1;
    margin-bottom: 0;
}

.cli-auth-row {
    height: auto;
    align: left middle;
    margin-bottom: 0;
}

.cli-auth-row.-spaced {
    margin-top: 1;
}

.cli-auth-row Input {
    margin-right: 1;
    background: #08111f;
    color: #e8f0ff;
    border: round #16314d;
}

.cli-auth-row Input.-tail {
    margin-right: 0;
}

.cli-auth-row Input:focus {
    border: round #5db4ff;
}

.cli-auth-row Button,
.cli-switch-row Button {
    width: 12;
    min-width: 10;
    content-align: center middle;
    background: #101d2e;
    color: #d9e8ff;
    border: round #1d3550;
}

.cli-auth-row Button:hover,
.cli-switch-row Button:hover {
    background: #15273d;
    border: round #355f8c;
}

.cli-auth-row Button:focus,
.cli-switch-row Button:focus {
    background: #18324f;
    border: round #8ac6ff;
    color: #ffffff;
}

.cli-auth-row Button:disabled,
.cli-switch-row Button:disabled {
    color: #6e8098;
    background: #0c1827;
    border: round #13273d;
}

.cli-toggle-button.-connect {
    background: #214a77;
    color: #ffffff;
    border: round #8ac6ff;
    text-style: bold;
}

.cli-toggle-button.-disconnect {
    background: #5a293b;
    color: #ffe7ef;
    border: round #f2a4c1;
    text-style: bold;
}

.cli-toggle-button.-connect:focus {
    background: #224468;
    border: round #a8dcff;
    color: #ffffff;
}

.cli-toggle-button.-disconnect:focus {
    background: #4a2634;
    border: round #f2a4c1;
    color: #fff3f8;
}

#linux-host-input {
    width: 1fr;
}

#linux-port-input {
    width: 6;
}

#linux-username-input {
    width: 1fr;
}

#linux-password-input {
    width: 1fr;
}

#device-username-input {
    width: 1fr;
}

#device-password-input {
    width: 1fr;
}

.cli-full-button {
    width: 1fr;
    min-width: 10;
}

#cli-log {
    height: 1fr;
    min-height: 3;
    border: round #2a4f75;
    background: #08111f;
    color: #d9e8ff;
    margin-top: 1;
    margin-bottom: 0;
}

#cli-command-bar {
    height: auto;
    margin-top: 1;
    margin-bottom: 0;
}

#cli-command-input {
    height: auto;
    margin-top: 0;
    margin-bottom: 0;
    background: #08111f;
    color: #e8f0ff;
    border: round #2a4f75;
}
"""


def status_color(status: str) -> str:
    palette = {
        STATUS_OCCUPIED: "#f4c861",
        STATUS_IDLE: "#35d07f",
        STATUS_PIPELINE: "#ffb65c",
        STATUS_OTHER: "#b88cff",
    }
    return palette.get(status, "#88a0ba")


def fit_cell(value: str, width: int, pad: bool = True) -> str:
    if width <= 0:
        return ""
    if cell_len(value) <= width:
        return set_cell_size(value, width) if pad else value
    if width <= 3:
        return "." * width

    trimmed = ""
    for char in value:
        if cell_len(trimmed + char) > width - 3:
            break
        trimmed += char
    fitted = f"{trimmed}..."
    return set_cell_size(fitted, width) if pad else fitted


def status_badge(status: str) -> str:
    labels = {
        STATUS_IDLE: "[\u7a7a\u95f2]",
        STATUS_OCCUPIED: "[\u5360\u7528]",
        STATUS_PIPELINE: "[\u6d41\u6c34\u7ebf]",
        STATUS_OTHER: "[\u5176\u4ed6]",
    }
    return labels.get(status, f"[{status}]")


class DeviceListItem(ListItem):
    def __init__(self, device: Device, row: Text, emphasis: bool = False) -> None:
        self.device = device
        self.row_label = Label(row)
        super().__init__(self.row_label)
        if emphasis:
            self.add_class("--highlight")

    def update_row(self, row: Text) -> None:
        self.row_label.update(row)

    def on_click(self, event: events.Click) -> None:
        if event.button != 1:
            return

        app = self.app
        if isinstance(app, DeviceDashboard):
            app.handle_device_item_click(self.device)
            event.stop()


class SuggestInput(Input):
    BINDINGS = [Binding("tab", "accept_suggestion", "Accept Suggestion", show=False)]

    def action_accept_suggestion(self) -> None:
        if self.cursor_at_end and self._suggestion:
            self.action_cursor_right()
        app = self.app
        if app is not None and hasattr(app, "action_focus_next"):
            app.action_focus_next()


class DeviceDashboard(App[None]):
    CSS = APP_CSS
    TITLE = "Network Device Center"
    SUB_TITLE = "RTN / XTN / Router / JQ"
    BINDINGS = [
        ("q", "quit", "Quit"),
        ("o", "toggle_occupy", "Claim/Release"),
        ("s", "ssh_connect", "SSH"),
        ("S", "ssh_connect_external", "SSH Window"),
        ("t", "telnet_connect", "Telnet"),
        ("T", "telnet_connect_external", "Telnet Window"),
        ("p", "toggle_password", "Password"),
        ("ctrl+d", "disconnect_cli", "Disconnect CLI"),
        ("ctrl+l", "focus_cli_command", "CLI Input"),
        ("ctrl+left", "move_split_left", "Split Left"),
        ("ctrl+right", "move_split_right", "Split Right"),
        ("ctrl+up", "move_split_up", "Split Up"),
        ("ctrl+down", "move_split_down", "Split Down"),
        ("ctrl+r", "reset_layout_split", "Reset Layout"),
        ("slash", "focus_filter", "Filter"),
        ("tab", "focus_next", "Next Pane"),
        ("shift+tab", "focus_previous", "Prev Pane"),
    ]

    selected_device_id = reactive("")
    filter_text = reactive("")
    filter_domain = reactive("")
    filter_status = reactive(ALL_STATUS)
    filter_cpu = reactive("")
    show_password = reactive(False)
    active_cli_auth = reactive("device")

    def __init__(self, repository: DeviceRepository | None = None) -> None:
        super().__init__()
        self.repository = repository or create_repository_from_env()
        self.current_user = self.repository.current_user()
        self.refresh_interval_seconds = getattr(self.repository, "refresh_interval_seconds", 0.0)
        self.live_update_timeout_seconds = getattr(self.repository, "live_update_timeout_seconds", 0.0)
        self.current_revision = 0
        self.devices: list[Device] = []
        self.search_index: dict[str, str] = {}
        self.visible_devices: list[Device] = []
        self.visible_owned_devices: list[Device] = []
        self.device_items: dict[str, DeviceListItem] = {}
        self.my_items: dict[str, DeviceListItem] = {}
        self.status_button_ids: dict[str, str] = {}
        self._repository_lock = asyncio.Lock()
        self._background_jobs: set[asyncio.Task[None]] = set()
        self._last_click_device_id = ""
        self._last_click_at = 0.0
        self._double_click_window_seconds = 0.45
        self._device_snapshot_signature: tuple[tuple[str | None, ...], ...] = ()
        self.device_cli_status_text = "Disconnected"
        self.linux_cli_status_text = "Disconnected"
        self.workflow_status_text = "Workflow idle"
        self.device_cli_session = HuaweiTelnetSession(
            on_output=lambda message: self.append_cli_channel_output("device", message),
            on_status=self.set_device_cli_status,
        )
        self.linux_cli_session = LinuxSshSession(
            SessionCallbacks(
                on_output=lambda message: self.append_cli_channel_output("linux", message),
                on_status=self.set_linux_cli_status,
            )
        )
        self.workflow_runner = WorkflowRunner(
            WorkflowContext(
                linux=self.linux_cli_session,
                device=self.device_cli_session,
                emit_output=lambda message: self.append_cli_channel_output("workflow", message),
                emit_status=self.set_workflow_status,
            )
        )
        self.device_cli_connecting = False
        self.linux_cli_connecting = False
        self.workflow_running = False
        self._quitting = False
        self._device_session_device_id = ""
        self._device_session_name = ""
        self._device_session_host = ""
        self._device_session_port = 23
        self._cli_defaults_device_id = ""
        self._cli_line_starts = {
            "device": True,
            "linux": True,
            "workflow": True,
            "system": True,
        }
        self.left_pane_fr = 2
        self.right_pane_fr = 1
        self.detail_pane_fr = 0
        self.cli_pane_fr = 7

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="shell"):
            with Vertical(id="left-pane"):
                with Container(id="device-panel", classes="panel"):
                    yield Label("Device List", classes="panel-title")
                    yield Static(
                        "\u5e8f\u53f7 / \u8bbe\u5907 / \u9886\u57df / CPU / \u72b6\u6001 / \u5360\u7528\u4eba",
                        classes="section-copy",
                    )
                    with Horizontal(id="toolbar-row"):
                        yield Input(
                            placeholder="\u641c\u7d22\u8bbe\u5907 / ID / SSH IP / Telnet IP / \u578b\u53f7",
                            id="filter-input",
                        )
                        yield Static(id="stats-strip")
                    with Vertical(id="filter-row"):
                        with Horizontal(id="status-row"):
                            yield from self.compose_status_chips()
                        with Horizontal(id="keyword-row"):
                            yield SuggestInput(
                                placeholder="\u9886\u57df\u5173\u952e\u5b57\uff0c\u4f8b\u5982 RTN / \u4ea4\u4f01 / \u6d4b\u8bd5",
                                id="domain-filter-input",
                                classes="keyword-filter",
                                suggester=SuggestFromList([], case_sensitive=False),
                            )
                            yield SuggestInput(
                                placeholder="CPU \u5173\u952e\u5b57\uff0c\u4f8b\u5982 ARM-0 / ARM-1",
                                id="cpu-filter-input",
                                classes="keyword-filter",
                                suggester=SuggestFromList([], case_sensitive=False),
                            )
                    yield Static(id="device-header", classes="list-header")
                    yield ListView(id="device-list")
                with Container(id="occupancy-panel", classes="panel"):
                    yield Label("My Occupancy", classes="panel-title")
                    yield Static(f"Current User: {self.current_user}", id="occupancy-meta", classes="section-copy")
                    yield Static(id="my-header", classes="list-header")
                    yield ListView(id="my-list")
            with Vertical(id="right-pane"):
                with Container(id="detail-panel", classes="panel"):
                    yield Label("Device Detail", classes="panel-title")
                    yield Static("\u8fde\u63a5 / \u8d44\u4ea7 / \u4f4d\u7f6e", classes="section-copy")
                    yield Static(id="detail-card")
                with Vertical(id="cli-panel", classes="panel"):
                    yield Label("CLI Session", classes="panel-title")
                    with Horizontal(classes="cli-switch-row"):
                        yield Button("Device", id="cli-switch-device", classes="cli-switch-button")
                        yield Button("Linux", id="cli-switch-linux", classes="cli-switch-button -last")
                    with Container(id="cli-auth-stack"):
                        with Container(id="device-auth-block", classes="cli-auth-block"):
                            with Horizontal(classes="cli-auth-row"):
                                yield Input(placeholder="Device Username", id="device-username-input")
                                yield Input(
                                    placeholder="Device Password",
                                    password=True,
                                    id="device-password-input",
                                )
                            with Horizontal(classes="cli-auth-row -spaced"):
                                yield Button(
                                    "Connect",
                                    id="device-toggle-button",
                                    classes="cli-toggle-button -connect cli-full-button",
                                )
                        with Container(id="linux-auth-block", classes="cli-auth-block"):
                            with Horizontal(classes="cli-auth-row"):
                                yield Input(placeholder="Linux Host", id="linux-host-input")
                                yield Input(value="22", placeholder="Port", id="linux-port-input", classes="-tail")
                            with Horizontal(classes="cli-auth-row"):
                                yield Input(placeholder="Linux Username", id="linux-username-input")
                                yield Input(
                                    placeholder="Linux Password",
                                    password=True,
                                    id="linux-password-input",
                                )
                            with Horizontal(classes="cli-auth-row -spaced"):
                                yield Button(
                                    "Connect",
                                    id="linux-toggle-button",
                                    classes="cli-toggle-button -connect cli-full-button",
                                )
                    yield Static("Command: device cmd | /workflow", id="cli-command-meta")
                    with Horizontal(id="cli-command-bar"):
                        yield Input(
                            placeholder="Enter device command or /workflow and press Enter",
                            id="cli-command-input",
                        )
                    yield RichLog(id="cli-log", wrap=True, markup=False, auto_scroll=True, highlight=False)
        yield Footer()

    def compose_status_chips(self) -> ComposeResult:
        with Horizontal(classes="chip-section"):
            yield Static("\u72b6\u6001", classes="chip-group-title")
            for index, status in enumerate([ALL_STATUS, *STATUS_ORDER]):
                button_id = f"status_chip_{index}"
                self.status_button_ids[status] = button_id
                yield Button(status, id=button_id, classes="filter-chip")

    def on_mount(self) -> None:
        self.apply_layout_split()
        self.refresh_headers()
        self.refresh_filter_chips()
        self.query_one("#stats-strip", Static).update(Text.from_markup("[#88a0ba]Loading...[/]"))
        self.query_one("#detail-card", Static).update(Text.from_markup("[#88a0ba]Loading devices...[/]"))
        self.set_device_cli_status("Disconnected")
        self.set_linux_cli_status("Disconnected")
        self.set_workflow_status("Workflow idle")
        self.refresh_cli_switch_buttons()
        self.update_cli_controls()
        self.append_cli_channel_output(
            "system",
            "Dual-channel console ready. Connect device Telnet and optional Linux SSH, then run commands.\n",
        )
        self.query_one("#device-list", ListView).focus()
        self.launch_background_job(self.reload_devices(show_errors=True))
        if self.live_update_timeout_seconds > 0:
            self.launch_background_job(self.watch_repository_updates())
        if self.refresh_interval_seconds > 0:
            self.set_interval(self.refresh_interval_seconds, self.enqueue_auto_refresh)

    def on_resize(self) -> None:
        self.apply_layout_split()
        self.refresh_headers()
        self.refresh_lists()
        self.update_detail(self.get_selected_device())

    def launch_background_job(self, coroutine: Coroutine[object, object, None]) -> None:
        task = asyncio.create_task(coroutine)
        self._background_jobs.add(task)
        task.add_done_callback(self._background_jobs.discard)

    def apply_layout_split(self) -> None:
        try:
            self.query_one("#left-pane", Vertical).styles.width = f"{self.left_pane_fr}fr"
            self.query_one("#right-pane", Vertical).styles.width = f"{self.right_pane_fr}fr"
            right_pane = self.query_one("#right-pane", Vertical)
            available_height = right_pane.size.height or max((self.size.height or 24) - 4, 16)
            gap_height = 1
            usable_height = max(available_height - gap_height, 10)
            total_units = max(self.detail_pane_fr + self.cli_pane_fr, 1)
            detail_height = max(1, int(usable_height * self.detail_pane_fr / total_units))
            cli_height = max(6, usable_height - detail_height)
            if detail_height + cli_height > usable_height:
                cli_height = max(6, usable_height - detail_height)

            self.query_one("#detail-panel", Container).styles.height = detail_height
            self.query_one("#cli-panel", Vertical).styles.height = cli_height
        except NoMatches:
            return

    def action_move_split_left(self) -> None:
        if self.left_pane_fr <= 1:
            return
        self.left_pane_fr -= 1
        self.right_pane_fr += 1
        self.apply_layout_split()
        self.refresh_headers()
        self.refresh_lists()

    def action_move_split_right(self) -> None:
        if self.right_pane_fr <= 1:
            return
        self.left_pane_fr += 1
        self.right_pane_fr -= 1
        self.apply_layout_split()
        self.refresh_headers()
        self.refresh_lists()

    def action_move_split_up(self) -> None:
        if self.detail_pane_fr <= 2:
            return
        self.detail_pane_fr -= 1
        self.cli_pane_fr += 1
        self.apply_layout_split()

    def action_move_split_down(self) -> None:
        if self.cli_pane_fr <= 2:
            return
        self.detail_pane_fr += 1
        self.cli_pane_fr -= 1
        self.apply_layout_split()

    def action_reset_layout_split(self) -> None:
        self.left_pane_fr = 2
        self.right_pane_fr = 1
        self.detail_pane_fr = 0
        self.cli_pane_fr = 7
        self.apply_layout_split()
        self.refresh_headers()
        self.refresh_lists()

    def append_cli_output(self, message: str) -> None:
        if self._quitting:
            return
        try:
            log = self.query_one("#cli-log", RichLog)
        except NoMatches:
            return
        log.write(message)

    def append_cli_channel_output(self, channel: str, message: str) -> None:
        normalized = message.replace("\r\n", "\n").replace("\r", "\n")
        at_line_start = self._cli_line_starts.get(channel, True)
        prefix = f"[{channel}] "
        parts: list[str] = []
        for char in normalized:
            if at_line_start and char != "\n":
                parts.append(prefix)
                at_line_start = False
            parts.append(char)
            if char == "\n":
                at_line_start = True
        self._cli_line_starts[channel] = at_line_start
        if parts:
            self.append_cli_output("".join(parts))

    def set_device_cli_status(self, status: str) -> None:
        self.device_cli_status_text = status
        if self._quitting:
            return
        self.update_cli_command_placeholder()

    def set_linux_cli_status(self, status: str) -> None:
        self.linux_cli_status_text = status
        if self._quitting:
            return
        self.update_cli_command_placeholder()

    def set_workflow_status(self, status: str) -> None:
        self.workflow_status_text = status
        if self._quitting:
            return
        self.update_cli_command_placeholder()

    def update_cli_command_placeholder(self) -> None:
        selected = self.get_selected_device()
        selected_name = selected.name if selected is not None else "no device"

        if self.workflow_running:
            placeholder = "Workflow is running..."
        elif self.device_cli_session.is_connected:
            placeholder = f"{selected_name}: display version  or  /collect_log"
        else:
            placeholder = f"{selected_name}: connect device first"

        try:
            self.query_one("#cli-command-input", Input).placeholder = placeholder
        except NoMatches:
            return

    def update_cli_command_meta(self, value: str = "") -> None:
        text = value.strip()
        if text.startswith("/"):
            if " " in text:
                command_part = text.split(" ", 1)[0]
            else:
                command_part = text
            matches = [command for command in WORKFLOW_COMMANDS if command.startswith(command_part) or command_part == "/"]
            if matches:
                meta = "Workflow: " + " | ".join(matches)
            else:
                meta = "Workflow: /collect_log | /change_cc <value>"
        else:
            meta = "Command: device cmd | /workflow"

        try:
            self.query_one("#cli-command-meta", Static).update(meta)
        except NoMatches:
            return

    def update_cli_controls(self) -> None:
        device_connected = self.device_cli_session.is_connected
        linux_connected = self.linux_cli_session.is_connected
        device_connecting = self.device_cli_connecting
        linux_connecting = self.linux_cli_connecting
        selected_device = self.get_selected_device()
        has_target = selected_device is not None and bool(selected_device.telnet_ip.strip())
        try:
            device_button = self.query_one("#device-toggle-button", Button)
            linux_button = self.query_one("#linux-toggle-button", Button)
            self.query_one("#device-username-input", Input).disabled = (
                device_connected or device_connecting or self.workflow_running
            )
            self.query_one("#device-password-input", Input).disabled = (
                device_connected or device_connecting or self.workflow_running
            )
            self.query_one("#linux-host-input", Input).disabled = (
                linux_connected or linux_connecting or self.workflow_running
            )
            self.query_one("#linux-port-input", Input).disabled = (
                linux_connected or linux_connecting or self.workflow_running
            )
            self.query_one("#linux-username-input", Input).disabled = (
                linux_connected or linux_connecting or self.workflow_running
            )
            self.query_one("#linux-password-input", Input).disabled = (
                linux_connected or linux_connecting or self.workflow_running
            )
            self.query_one("#cli-command-input", Input).disabled = (
                not device_connected or self.workflow_running
            )
        except NoMatches:
            return
        device_button.disabled = (
            device_connecting
            or self.workflow_running
            or (not device_connected and not has_target)
        )
        device_button.label = "Disconnect" if device_connected else "Connect"
        device_button.set_class(not device_connected, "-connect")
        device_button.set_class(device_connected, "-disconnect")

        linux_button.disabled = linux_connecting or self.workflow_running
        linux_button.label = "Disconnect" if linux_connected else "Connect"
        linux_button.set_class(not linux_connected, "-connect")
        linux_button.set_class(linux_connected, "-disconnect")
        self.update_cli_command_placeholder()
        command_value = ""
        try:
            command_value = self.query_one("#cli-command-input", Input).value
        except NoMatches:
            command_value = ""
        self.update_cli_command_meta(command_value)
        self.refresh_cli_switch_buttons()

    def refresh_cli_switch_buttons(self) -> None:
        try:
            device_switch = self.query_one("#cli-switch-device", Button)
            linux_switch = self.query_one("#cli-switch-linux", Button)
            device_block = self.query_one("#device-auth-block", Container)
            linux_block = self.query_one("#linux-auth-block", Container)
        except NoMatches:
            return

        device_block.display = self.active_cli_auth == "device"
        linux_block.display = self.active_cli_auth == "linux"
        device_switch.set_class(self.active_cli_auth == "device", "-active")
        linux_switch.set_class(self.active_cli_auth == "linux", "-active")

    def sync_cli_defaults_from_device(self, device: Device | None) -> None:
        if device is None:
            self._cli_defaults_device_id = ""
            self.update_cli_controls()
            return

        if self.device_cli_session.is_connected or self.device_cli_connecting:
            self.update_cli_controls()
            return

        username_input = self.query_one("#device-username-input", Input)
        password_input = self.query_one("#device-password-input", Input)
        linux_host_input = self.query_one("#linux-host-input", Input)
        linux_port_input = self.query_one("#linux-port-input", Input)
        linux_username_input = self.query_one("#linux-username-input", Input)
        linux_password_input = self.query_one("#linux-password-input", Input)
        is_mock_lab = device.id == "MOCK-LAB-000"

        if self._cli_defaults_device_id != device.id:
            username_input.value = device.username
            password_input.value = device.password
            if not self.linux_cli_session.is_connected and not self.linux_cli_connecting:
                linux_host_input.value = device.ssh_ip
                linux_port_input.value = str(device.ssh_port)
                if is_mock_lab:
                    linux_username_input.value = "ops"
                    linux_password_input.value = "ops123"
            self._cli_defaults_device_id = device.id
            self.update_cli_controls()
            return

        if not username_input.value:
            username_input.value = device.username
        if not password_input.value:
            password_input.value = device.password
        if not self.linux_cli_session.is_connected and not self.linux_cli_connecting:
            if not linux_host_input.value:
                linux_host_input.value = device.ssh_ip
            if not linux_port_input.value:
                linux_port_input.value = str(device.ssh_port)
            if is_mock_lab:
                if not linux_username_input.value:
                    linux_username_input.value = "ops"
                if not linux_password_input.value:
                    linux_password_input.value = "ops123"
        self.update_cli_controls()

    def enqueue_auto_refresh(self) -> None:
        if self._repository_lock.locked():
            return
        self.launch_background_job(self.reload_devices(show_errors=False))

    async def watch_repository_updates(self) -> None:
        while True:
            try:
                revision = await asyncio.to_thread(
                    self.repository.wait_for_update,
                    self.current_revision,
                    self.live_update_timeout_seconds,
                )
            except RepositoryError as exc:
                self.notify(str(exc), severity="error", timeout=3)
                await asyncio.sleep(2)
                continue

            if revision is None:
                continue

            await self.reload_devices(
                show_errors=False,
                preferred_selection=self.selected_device_id or None,
            )

    async def reload_devices(
        self,
        show_errors: bool,
        preferred_selection: str | None = None,
    ) -> None:
        if self._repository_lock.locked():
            return
        async with self._repository_lock:
            try:
                devices = await asyncio.to_thread(self.repository.fetch_devices)
            except RepositoryError as exc:
                if show_errors:
                    self.notify(str(exc), severity="error", timeout=3)
                return
        self.apply_device_snapshot(devices, preferred_selection=preferred_selection)

    async def sync_toggle_occupancy(self, device_id: str) -> None:
        async with self._repository_lock:
            try:
                message = await asyncio.to_thread(
                    self.repository.toggle_device,
                    device_id,
                    self.current_user,
                )
                devices = await asyncio.to_thread(self.repository.fetch_devices)
            except RepositoryConflictError as exc:
                self.notify(str(exc), severity="warning", timeout=3)
                devices = await asyncio.to_thread(self.repository.fetch_devices)
                self.apply_device_snapshot(devices, preferred_selection=device_id)
                return
            except RepositoryError as exc:
                self.notify(str(exc), severity="error", timeout=3)
                return

        self.apply_device_snapshot(devices, preferred_selection=device_id)
        self.notify(message, timeout=2)

    def apply_device_snapshot(
        self,
        devices: list[Device],
        preferred_selection: str | None = None,
    ) -> None:
        current_user = self.repository.current_user()
        current_revision = self.repository.current_revision()
        snapshot_signature = self.build_device_snapshot_signature(devices)
        selection_before = self.selected_device_id
        selection_after = preferred_selection if preferred_selection is not None else selection_before
        snapshot_changed = snapshot_signature != self._device_snapshot_signature
        selection_changed = selection_after != selection_before
        current_user_changed = current_user != self.current_user

        self.current_user = current_user
        self.current_revision = current_revision

        if current_user_changed:
            self.query_one("#occupancy-meta", Static).update(f"Current User: {self.current_user}")

        if not snapshot_changed and not selection_changed:
            return

        self._device_snapshot_signature = snapshot_signature
        self.devices = devices
        self.search_index = {
            device.id: " ".join(
                [
                    device.id,
                    device.name,
                    device.ssh_ip,
                    str(device.ssh_port),
                    device.telnet_ip,
                    str(device.telnet_port),
                    device.model,
                ]
            ).lower()
            for device in self.devices
        }
        if preferred_selection is not None:
            self.selected_device_id = preferred_selection
        self.compute_visible_devices()
        self.refresh_filter_suggestions()
        self.refresh_filter_chips()
        self.refresh_headers()
        self.refresh_lists()
        self.ensure_valid_selection()
        selected = self.get_selected_device()
        self.update_detail(selected)
        self.sync_cli_defaults_from_device(selected)

    def build_device_snapshot_signature(
        self,
        devices: list[Device],
    ) -> tuple[tuple[object, ...], ...]:
        return tuple(
            (
                device.id,
                device.name,
                device.domain,
                device.device_type,
                device.cpu,
                device.status,
                device.owner,
                device.ssh_ip,
                device.ssh_port,
                device.telnet_ip,
                device.telnet_port,
                device.username,
                device.password,
                device.vendor,
                device.model,
                device.site,
                device.rack,
                device.version,
                device.notes,
            )
            for device in devices
        )

    def domain_values(self) -> list[str]:
        return sorted({device.domain for device in self.devices if device.domain})

    def cpu_values(self) -> list[str]:
        return sorted({device.cpu for device in self.devices if device.cpu})

    def refresh_filter_suggestions(self) -> None:
        domain_candidates = sorted({device.domain for device in self.visible_devices if device.domain})
        cpu_candidates = sorted({device.cpu for device in self.visible_devices if device.cpu})
        self.query_one("#domain-filter-input", Input).suggester = SuggestFromList(
            domain_candidates or self.domain_values(),
            case_sensitive=False,
        )
        self.query_one("#cpu-filter-input", Input).suggester = SuggestFromList(
            cpu_candidates or self.cpu_values(),
            case_sensitive=False,
        )

    def compute_visible_devices(self) -> None:
        keyword = self.filter_text.strip().lower()
        domain_keyword = self.filter_domain.strip().lower()
        cpu_keyword = self.filter_cpu.strip().lower()
        filtered: list[Device] = []
        for device in self.devices:
            if domain_keyword and domain_keyword not in device.domain.lower():
                continue
            if self.filter_status != ALL_STATUS and device.status != self.filter_status:
                continue
            if cpu_keyword and cpu_keyword not in device.cpu.lower():
                continue
            if keyword and keyword not in self.search_index.get(device.id, ""):
                continue
            filtered.append(device)

        self.visible_devices = filtered
        self.visible_owned_devices = [
            device for device in filtered if device.owner == self.current_user
        ]

    def refresh_filter_chips(self) -> None:
        for status, button_id in self.status_button_ids.items():
            self.query_one(f"#{button_id}", Button).set_class(status == self.filter_status, "-active")

    def update_stats(self) -> None:
        counts = {status: 0 for status in STATUS_ORDER}
        for device in self.visible_devices:
            if device.status in counts:
                counts[device.status] += 1

        stats_text = (
            f"[bold #8ac6ff]\u603b\u6570[/] {len(self.visible_devices)}    "
            f"[bold #f4c861]\u5df2\u5360\u7528[/] {counts[STATUS_OCCUPIED]}    "
            f"[bold #35d07f]\u7a7a\u95f2[/] {counts[STATUS_IDLE]}    "
            f"[bold #ffb65c]\u6d41\u6c34\u7ebf[/] {counts[STATUS_PIPELINE]}    "
            f"[bold #b88cff]\u5176\u4ed6[/] {counts[STATUS_OTHER]}"
        )
        self.query_one("#stats-strip", Static).update(Text.from_markup(stats_text))

    def main_columns(self) -> list[tuple[str, int]]:
        width = self.query_one("#device-list", ListView).size.width or 84
        if width < 62:
            no_width = 4
            domain_width = 6
            cpu_width = 6
            status_width = 8
            device_width = min(
                22,
                max(10, width - (no_width + domain_width + cpu_width + status_width + 4)),
            )
            return [
                ("No", no_width),
                ("Device", device_width),
                ("Domain", domain_width),
                ("CPU", cpu_width),
                ("Status", status_width),
            ]

        no_width = 4
        domain_width = 6
        cpu_width = 6
        status_width = 10
        owner_width = 10
        device_width = min(
            28,
            max(12, width - (no_width + domain_width + cpu_width + status_width + owner_width + 5)),
        )
        return [
            ("No", no_width),
            ("Device", device_width),
            ("Domain", domain_width),
            ("CPU", cpu_width),
            ("Status", status_width),
            ("Owner", owner_width),
        ]

    def occupancy_columns(self) -> list[tuple[str, int]]:
        width = self.query_one("#my-list", ListView).size.width or 64
        no_width = 4
        domain_width = 8
        device_width = min(26, max(12, width - (no_width + domain_width + 2)))
        return [
            ("No", no_width),
            ("Device", device_width),
            ("Domain", domain_width),
        ]

    def render_header(self, compact: bool = False) -> Text:
        columns = self.occupancy_columns() if compact else self.main_columns()
        header = Text()
        for index, (name, width) in enumerate(columns):
            if index:
                header.append(" ")
            header.append(fit_cell(name, width), style="bold #7d93ad")
        return header

    def render_row(self, device: Device, sequence: int, compact: bool = False) -> Text:
        columns = self.occupancy_columns() if compact else self.main_columns()
        owner = device.owner or "-"
        value_map = {
            "No": (str(sequence), "#7d93ad"),
            "Device": (device.name, "#ffffff"),
            "Domain": (device.domain, "#88a0ba"),
            "CPU": (device.cpu, "#5db4ff"),
            "Status": (status_badge(device.status), status_color(device.status)),
            "Owner": (owner, "#5db4ff" if owner == self.current_user else "#9cb4ce"),
        }

        row = Text()
        for index, (name, width) in enumerate(columns):
            value, tone = value_map[name]
            if index:
                row.append(" ")
            row.append(fit_cell(value, width), style=tone)
        return row

    def refresh_headers(self) -> None:
        self.query_one("#device-header", Static).update(self.render_header())
        self.query_one("#my-header", Static).update(self.render_header(compact=True))

    def refresh_lists(self) -> None:
        device_list = self.query_one("#device-list", ListView)
        my_list = self.query_one("#my-list", ListView)

        self.update_stats()
        device_list.clear()
        my_list.clear()
        self.device_items.clear()
        self.my_items.clear()

        for index, device in enumerate(self.visible_devices, start=1):
            item = DeviceListItem(
                device,
                row=self.render_row(device, sequence=index),
                emphasis=device.id == self.selected_device_id,
            )
            self.device_items[device.id] = item
            device_list.append(item)

        for index, device in enumerate(self.visible_owned_devices, start=1):
            item = DeviceListItem(
                device,
                row=self.render_row(device, sequence=index, compact=True),
                emphasis=device.id == self.selected_device_id,
            )
            self.my_items[device.id] = item
            my_list.append(item)

        if self.visible_devices:
            device_list.index = max(
                0,
                next((i for i, d in enumerate(self.visible_devices) if d.id == self.selected_device_id), 0),
            )
        if self.visible_owned_devices:
            my_list.index = max(
                0,
                next((i for i, d in enumerate(self.visible_owned_devices) if d.id == self.selected_device_id), 0),
            )

        self.sync_selection_styles()

    def ensure_valid_selection(self) -> None:
        if not self.visible_devices:
            self.selected_device_id = ""
            self.query_one("#detail-card", Static).update(
                Text.from_markup("[#88a0ba]No devices match the current filter.[/]")
            )
            return
        visible_ids = {device.id for device in self.visible_devices}
        if self.selected_device_id not in visible_ids:
            self.selected_device_id = self.visible_devices[0].id

    def get_device_by_id(self, device_id: str) -> Device | None:
        return next((device for device in self.devices if device.id == device_id), None)

    def get_selected_device(self) -> Device | None:
        if not self.selected_device_id:
            return None
        return self.get_device_by_id(self.selected_device_id)

    def sync_selection_styles(self) -> None:
        for device_id, item in self.device_items.items():
            item.set_class(device_id == self.selected_device_id, "--highlight")
        for device_id, item in self.my_items.items():
            item.set_class(device_id == self.selected_device_id, "--highlight")

    def update_detail(self, device: Device | None) -> None:
        if device is None:
            self.query_one("#detail-card", Static).update(
                Text.from_markup("[#88a0ba]No devices match the current filter.[/]")
            )
            return

        owner = device.owner or "Unassigned"
        owner_tone = "#5db4ff" if device.owner == self.current_user else "#c9d8ea"
        status_tone = status_color(device.status)
        password = device.password if self.show_password else "*" * max(8, len(device.password))
        detail = (
            f"[bold white]{device.name}[/]\n"
            f"[#88a0ba]{device.id}  |  {device.domain}  |  {device.device_type}[/]\n\n"
            f"[bold #5db4ff]Conn[/]  SSH {device.ssh_ip}:{device.ssh_port}  |  Telnet {device.telnet_ip}:{device.telnet_port}\n"
            f"[bold #5db4ff]Auth[/]  {device.username}  |  {password}\n"
            f"[bold #5db4ff]Asset[/]  [{status_tone}]{device.status}[/]  |  [{owner_tone}]{owner}[/]\n"
            f"[bold #5db4ff]Spec[/]  {device.cpu}  |  {device.vendor}  |  {device.model}\n"
            f"[bold #5db4ff]Ver[/]   {device.version}\n"
            f"[bold #5db4ff]Site[/]  {device.site}  |  {device.rack}\n\n"
            f"[bold #5db4ff]Notes[/] {device.notes}"
        )
        self.query_one("#detail-card", Static).update(Text.from_markup(detail))

    def select_device(self, device: Device) -> None:
        if self.selected_device_id == device.id:
            self.update_detail(device)
            self.sync_cli_defaults_from_device(device)
            return
        self.selected_device_id = device.id
        self.sync_selection_styles()
        self.update_detail(device)
        self.sync_cli_defaults_from_device(device)

    def handle_device_item_click(self, device: Device) -> None:
        self.select_device(device)
        clicked_at = time.monotonic()
        if (
            self._last_click_device_id == device.id
            and clicked_at - self._last_click_at <= self._double_click_window_seconds
        ):
            self._last_click_device_id = ""
            self._last_click_at = 0.0
            self.request_toggle_for_device(device.id)
            return

        self._last_click_device_id = device.id
        self._last_click_at = clicked_at

    def device_cli_connection_params(self) -> tuple[str, int, str, str, Device] | None:
        device = self.get_selected_device()
        if device is None or not device.telnet_ip.strip():
            self.notify("Select a device with a Telnet IP first", severity="warning", timeout=3)
            return None

        host = device.telnet_ip.strip()
        port = device.telnet_port
        username = self.query_one("#device-username-input", Input).value.strip()
        password = self.query_one("#device-password-input", Input).value

        if not host or not username or not password:
            self.notify("Username and password are required", severity="warning", timeout=3)
            return None

        return host, port, username, password, device

    def linux_cli_connection_params(self) -> tuple[str, int, str, str] | None:
        host = self.query_one("#linux-host-input", Input).value.strip()
        port_text = self.query_one("#linux-port-input", Input).value.strip() or "22"
        username = self.query_one("#linux-username-input", Input).value.strip()
        password = self.query_one("#linux-password-input", Input).value

        if not host or not username or not password:
            self.notify("Linux host, username, and password are required", severity="warning", timeout=3)
            return None

        try:
            port = int(port_text)
        except ValueError:
            self.notify("Linux port must be a number", severity="warning", timeout=3)
            return None

        return host, port, username, password

    def request_toggle_for_device(self, device_id: str) -> None:
        self.launch_background_job(self.sync_toggle_occupancy(device_id))

    async def connect_device_cli_session(self) -> None:
        if self.device_cli_session.is_connected:
            self.notify("Device channel is already connected", timeout=2)
            return

        params = self.device_cli_connection_params()
        if params is None:
            return

        host, port, username, password, device = params
        self.device_cli_connecting = True
        self.set_device_cli_status("Connecting")
        self.update_cli_controls()
        self._device_session_device_id = device.id
        self._device_session_name = device.name
        self._device_session_host = host
        self._device_session_port = port

        try:
            await self.device_cli_session.connect(host, port, username, password)
        except (OSError, asyncio.TimeoutError, TelnetSessionError) as exc:
            self.append_cli_channel_output("system", f"\nDevice connection failed: {exc}\n")
            await self.device_cli_session.disconnect("")
            self._device_session_device_id = ""
            self._device_session_name = ""
            self._device_session_host = ""
            self._device_session_port = 23
            self.set_device_cli_status("Disconnected")
            self.notify(str(exc), severity="error", timeout=4)
        finally:
            self.device_cli_connecting = False
            self.update_cli_controls()

        if self.device_cli_session.is_connected:
            self.query_one("#cli-command-input", Input).focus()

    async def connect_linux_cli_session(self) -> None:
        if self.linux_cli_session.is_connected:
            self.notify("Linux channel is already connected", timeout=2)
            return

        params = self.linux_cli_connection_params()
        if params is None:
            return

        host, port, username, password = params
        self.linux_cli_connecting = True
        self.set_linux_cli_status("Connecting")
        self.update_cli_controls()

        try:
            await self.linux_cli_session.connect(host, port, username, password)
        except SessionUnavailableError as exc:
            self.append_cli_channel_output("system", f"\nLinux connection failed: {exc}\n")
            await self.linux_cli_session.disconnect("")
            self.set_linux_cli_status("Disconnected")
            self.notify(str(exc), severity="error", timeout=4)
        finally:
            self.linux_cli_connecting = False
            self.update_cli_controls()

    async def disconnect_device_cli_session(self, message: str = "Disconnected.") -> None:
        self.device_cli_connecting = False
        self._device_session_device_id = ""
        self._device_session_name = ""
        self._device_session_host = ""
        self._device_session_port = 23
        if not self.device_cli_session.is_connected:
            self.set_device_cli_status("Disconnected")
            self.update_cli_controls()
            return
        await self.device_cli_session.disconnect(message)
        self.update_cli_controls()

    async def disconnect_linux_cli_session(self, message: str = "Disconnected.") -> None:
        self.linux_cli_connecting = False
        if not self.linux_cli_session.is_connected:
            self.set_linux_cli_status("Disconnected")
            self.update_cli_controls()
            return
        await self.linux_cli_session.disconnect(message)
        self.update_cli_controls()

    async def disconnect_all_cli_sessions(self, message: str = "Disconnected.") -> None:
        if self.workflow_running:
            self.notify("Wait for the workflow to finish before disconnecting channels", timeout=3)
            return
        await self.disconnect_device_cli_session(message)
        await self.disconnect_linux_cli_session(message)

    async def run_cli_workflow(self, command: str) -> None:
        try:
            request = parse_workflow_input(command)
        except WorkflowParseError as exc:
            self.append_cli_channel_output("system", f"\nWorkflow parse error: {exc}\n")
            self.notify(str(exc), severity="warning", timeout=3)
            return

        self.workflow_running = True
        self.update_cli_controls()
        try:
            await self.workflow_runner.run(request)
        except WorkflowExecutionError as exc:
            self.append_cli_channel_output("system", f"\nWorkflow failed: {exc}\n")
            self.notify(str(exc), severity="error", timeout=4)
        finally:
            self.workflow_running = False
            self.set_workflow_status("Workflow idle")
            self.update_cli_controls()

    async def send_cli_command(self, command: str) -> None:
        command_input = self.query_one("#cli-command-input", Input)
        command_input.value = ""
        self.update_cli_command_meta("")

        if self.workflow_running:
            self.notify("Workflow is running, please wait", timeout=2)
            return

        if command.startswith("/"):
            await self.run_cli_workflow(command)
            return

        if not self.device_cli_session.is_connected:
            self.notify("Device channel is not connected", severity="warning", timeout=3)
            return

        try:
            await self.device_cli_session.send_command(command)
        except TelnetSessionError as exc:
            self.notify(str(exc), severity="error", timeout=3)

    def action_disconnect_cli(self) -> None:
        self.launch_background_job(self.disconnect_all_cli_sessions())

    def action_focus_cli_command(self) -> None:
        if self.query_one("#cli-command-input", Input).disabled:
            self.notify("Device channel is not ready", timeout=2)
            return
        self.query_one("#cli-command-input", Input).focus()

    def action_focus_filter(self) -> None:
        self.query_one("#filter-input", Input).focus()

    async def action_quit(self) -> None:
        if self._quitting:
            return
        self._quitting = True

        tasks = [task for task in self._background_jobs if task is not asyncio.current_task()]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._background_jobs.clear()

        await self.disconnect_device_cli_session("")
        await self.disconnect_linux_cli_session("")
        self.exit()

    def run_external_command(self, command: list[str]) -> None:
        with self.suspend():
            subprocess.run(command, check=False)

    def launch_detached_terminal(self, title: str, command: str) -> bool:
        wt_path = shutil.which("wt")
        if wt_path:
            subprocess.Popen(
                [wt_path, "new-tab", "--title", title, "powershell", "-NoExit", "-Command", command],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True

        powershell_path = shutil.which("powershell")
        if powershell_path:
            subprocess.Popen(
                [
                    powershell_path,
                    "-NoProfile",
                    "-Command",
                    f"Start-Process powershell -ArgumentList '-NoExit','-Command','{command}'",
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True

        return False

    def action_toggle_password(self) -> None:
        if not self.selected_device_id:
            return
        self.show_password = not self.show_password
        self.update_detail(self.get_selected_device())
        message = "Password visible" if self.show_password else "Password hidden"
        self.notify(message, timeout=2)

    def action_ssh_connect(self) -> None:
        device = self.get_selected_device()
        if device is None:
            return
        if shutil.which("ssh") is None:
            self.notify("ssh command not found", severity="error", timeout=3)
            return

        self.run_external_command(["ssh", "-p", str(device.ssh_port), f"{device.username}@{device.ssh_ip}"])
        self.notify(f"SSH closed: {device.name}", timeout=2)

    def action_ssh_connect_external(self) -> None:
        device = self.get_selected_device()
        if device is None:
            return
        if shutil.which("ssh") is None:
            self.notify("ssh command not found", severity="error", timeout=3)
            return

        launched = self.launch_detached_terminal(
            title=device.name,
            command=f"ssh -p {device.ssh_port} {device.username}@{device.ssh_ip}",
        )
        if launched:
            self.notify(f"Opened SSH window: {device.name}", timeout=2)
        else:
            self.notify("No terminal launcher found", severity="error", timeout=3)

    def action_telnet_connect(self) -> None:
        device = self.get_selected_device()
        if device is None:
            return
        if shutil.which("telnet") is None:
            self.notify("telnet command not found", severity="error", timeout=3)
            return

        self.run_external_command(["telnet", device.telnet_ip, str(device.telnet_port)])
        self.notify(f"Telnet closed: {device.name}", timeout=2)

    def action_telnet_connect_external(self) -> None:
        device = self.get_selected_device()
        if device is None:
            return
        if shutil.which("telnet") is None:
            self.notify("telnet command not found", severity="error", timeout=3)
            return

        launched = self.launch_detached_terminal(
            title=device.name,
            command=f"telnet {device.telnet_ip} {device.telnet_port}",
        )
        if launched:
            self.notify(f"Opened Telnet window: {device.name}", timeout=2)
        else:
            self.notify("No terminal launcher found", severity="error", timeout=3)

    def refresh_filtered_view(self) -> None:
        self.compute_visible_devices()
        self.refresh_filter_suggestions()
        self.refresh_filter_chips()
        self.refresh_headers()
        self.refresh_lists()
        self.ensure_valid_selection()
        self.update_detail(self.get_selected_device())

    @on(Input.Changed, "#filter-input")
    def handle_filter_changed(self, event: Input.Changed) -> None:
        self.filter_text = event.value
        self.refresh_filtered_view()

    @on(Button.Pressed, ".filter-chip")
    def handle_filter_chip_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        for status, status_button_id in self.status_button_ids.items():
            if button_id == status_button_id:
                self.filter_status = status
                self.refresh_filtered_view()
                return

    @on(Input.Changed, "#domain-filter-input")
    def handle_domain_changed(self, event: Input.Changed) -> None:
        if event.value == self.filter_domain:
            return
        self.filter_domain = event.value
        self.refresh_filtered_view()

    @on(Input.Changed, "#cpu-filter-input")
    def handle_cpu_changed(self, event: Input.Changed) -> None:
        if event.value == self.filter_cpu:
            return
        self.filter_cpu = event.value
        self.refresh_filtered_view()

    @on(Input.Changed, "#cli-command-input")
    def handle_cli_command_changed(self, event: Input.Changed) -> None:
        self.update_cli_command_meta(event.value)

    @on(Button.Pressed, "#cli-switch-device")
    def handle_cli_switch_device_pressed(self) -> None:
        self.active_cli_auth = "device"
        self.refresh_cli_switch_buttons()

    @on(Button.Pressed, "#cli-switch-linux")
    def handle_cli_switch_linux_pressed(self) -> None:
        self.active_cli_auth = "linux"
        self.refresh_cli_switch_buttons()

    @on(Button.Pressed, "#device-toggle-button")
    def handle_device_cli_toggle_pressed(self) -> None:
        if self.device_cli_session.is_connected:
            self.launch_background_job(self.disconnect_device_cli_session())
            return
        self.launch_background_job(self.connect_device_cli_session())

    @on(Button.Pressed, "#linux-toggle-button")
    def handle_linux_cli_toggle_pressed(self) -> None:
        if self.linux_cli_session.is_connected:
            self.launch_background_job(self.disconnect_linux_cli_session())
            return
        self.launch_background_job(self.connect_linux_cli_session())

    @on(Input.Submitted, "#cli-command-input")
    def handle_cli_command_submitted(self, event: Input.Submitted) -> None:
        command = event.value.strip()
        if not command:
            return
        self.launch_background_job(self.send_cli_command(command))

    @on(ListView.Selected, "#device-list")
    def handle_device_selected(self, event: ListView.Selected) -> None:
        if isinstance(event.item, DeviceListItem):
            self.select_device(event.item.device)

    @on(ListView.Highlighted, "#device-list")
    def handle_device_highlighted(self, event: ListView.Highlighted) -> None:
        if event.item and isinstance(event.item, DeviceListItem):
            self.select_device(event.item.device)

    @on(ListView.Selected, "#my-list")
    def handle_my_selected(self, event: ListView.Selected) -> None:
        if isinstance(event.item, DeviceListItem):
            self.select_device(event.item.device)

    @on(ListView.Highlighted, "#my-list")
    def handle_my_highlighted(self, event: ListView.Highlighted) -> None:
        if event.item and isinstance(event.item, DeviceListItem):
            self.select_device(event.item.device)

    def action_toggle_occupy(self) -> None:
        if not self.selected_device_id:
            return
        self.request_toggle_for_device(self.selected_device_id)


def main() -> None:
    DeviceDashboard().run()
    print("", flush=True)


if __name__ == "__main__":
    main()

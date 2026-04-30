from __future__ import annotations

import shutil
import subprocess

from rich.cells import cell_len, set_cell_size
from rich.text import Text
from textual import events, on
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.reactive import reactive
from textual.suggester import SuggestFromList
from textual.widgets import Button, Footer, Header, Input, Label, ListItem, ListView, Static

from data import CURRENT_USER, Device, sample_devices


ALL_STATUS = "\u5168\u90e8\u72b6\u6001"
STATUS_OCCUPIED = "\u5df2\u88ab\u5360\u7528"
STATUS_IDLE = "\u7a7a\u95f2"
STATUS_PIPELINE = "\u6d41\u6c34\u7ebf\u5360\u7528"
STATUS_OTHER = "\u5176\u4ed6"
STATUS_ORDER = [STATUS_OCCUPIED, STATUS_IDLE, STATUS_PIPELINE, STATUS_OTHER]


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
}

.panel {
    border: tall #24415f;
    background: #0d1726;
    padding: 1;
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
    background: #101d2e;
    color: #b8c9dd;
    border: round #1d3550;
}

.filter-chip:hover {
    background: #15273d;
    border: round #355f8c;
}

.filter-chip.-active {
    background: #1b395d;
    color: #ffffff;
    border: round #5db4ff;
    text-style: bold;
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
}

ListItem.--highlight {
    background: #143052;
}

#detail-card {
    border: round #2a4f75;
    background: #0a1422;
    padding: 1 2;
    height: 1fr;
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
        STATUS_IDLE: "[空闲]",
        STATUS_OCCUPIED: "[占用]",
        STATUS_PIPELINE: "[流水线]",
        STATUS_OTHER: "[其他]",
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
        if event.button != 1 or event.chain != 2:
            return

        app = self.app
        if isinstance(app, DeviceDashboard):
            app.select_device(self.device)
            app.call_after_refresh(app.toggle_occupancy_for_device, self.device)
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

    def __init__(self) -> None:
        super().__init__()
        self.devices = sample_devices()
        self.search_index = {
            device.id: " ".join(
                [
                    device.id,
                    device.name,
                    device.ssh_ip,
                    device.telnet_ip,
                    device.model,
                ]
            ).lower()
            for device in self.devices
        }
        self.visible_devices: list[Device] = self.devices[:]
        self.visible_owned_devices: list[Device] = []
        self.device_items: dict[str, DeviceListItem] = {}
        self.my_items: dict[str, DeviceListItem] = {}
        self.status_button_ids: dict[str, str] = {}

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="shell"):
            with Vertical(id="left-pane"):
                with Container(id="device-panel", classes="panel"):
                    yield Label("Device List", classes="panel-title")
                    yield Static("\u5e8f\u53f7 / \u8bbe\u5907 / \u9886\u57df / CPU / \u72b6\u6001 / \u5360\u7528\u4eba", classes="section-copy")
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
                                suggester=SuggestFromList(self.domain_values(), case_sensitive=False),
                            )
                            yield SuggestInput(
                                placeholder="CPU \u5173\u952e\u5b57\uff0c\u4f8b\u5982 hi12 / kunpeng / x86",
                                id="cpu-filter-input",
                                classes="keyword-filter",
                                suggester=SuggestFromList(self.cpu_values(), case_sensitive=False),
                            )
                    yield Static(id="device-header", classes="list-header")
                    yield ListView(id="device-list")
                with Container(id="occupancy-panel", classes="panel"):
                    yield Label("My Occupancy", classes="panel-title")
                    yield Static(f"Current User: {CURRENT_USER}", id="occupancy-meta", classes="section-copy")
                    yield Static(id="my-header", classes="list-header")
                    yield ListView(id="my-list")
            with Container(id="right-pane", classes="panel"):
                yield Label("Device Detail", classes="panel-title")
                yield Static("\u8fde\u63a5 / \u8d44\u4ea7 / \u4f4d\u7f6e", classes="section-copy")
                yield Static(id="detail-card")
        yield Footer()

    def compose_status_chips(self) -> ComposeResult:
        with Horizontal(classes="chip-section"):
            yield Static("\u72b6\u6001", classes="chip-group-title")
            for index, status in enumerate([ALL_STATUS, *STATUS_ORDER]):
                button_id = f"status_chip_{index}"
                self.status_button_ids[status] = button_id
                yield Button(status, id=button_id, classes="filter-chip")

    def on_mount(self) -> None:
        self.selected_device_id = self.devices[0].id
        self.compute_visible_devices()
        self.refresh_filter_suggestions()
        self.refresh_filter_chips()
        self.refresh_headers()
        self.refresh_lists()
        self.ensure_valid_selection()
        self.update_detail(self.get_selected_device())
        self.query_one("#device-list", ListView).focus()

    def on_resize(self) -> None:
        self.refresh_headers()
        self.refresh_lists()
        if self.selected_device_id:
            self.update_detail(self.get_selected_device())

    def domain_values(self) -> list[str]:
        return sorted({device.domain for device in self.devices})

    def cpu_values(self) -> list[str]:
        return sorted({device.cpu for device in self.devices})

    def refresh_filter_suggestions(self) -> None:
        domain_candidates = sorted({device.domain for device in self.visible_devices})
        cpu_candidates = sorted({device.cpu for device in self.visible_devices})
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
            if keyword and keyword not in self.search_index[device.id]:
                continue
            filtered.append(device)

        self.visible_devices = filtered
        self.visible_owned_devices = [
            device for device in filtered if device.owner == CURRENT_USER
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
            "ID": (device.id, "#c9d8ea"),
            "Device": (device.name, "#ffffff"),
            "Domain": (device.domain, "#88a0ba"),
            "CPU": (device.cpu, "#5db4ff"),
            "Status": (status_badge(device.status), status_color(device.status)),
            "Owner": (owner, "#5db4ff" if owner == CURRENT_USER else "#9cb4ce"),
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
        if self.selected_device_id not in {device.id for device in self.visible_devices}:
            self.selected_device_id = self.visible_devices[0].id

    def get_selected_device(self) -> Device:
        return next(device for device in self.devices if device.id == self.selected_device_id)

    def sync_selection_styles(self) -> None:
        for device_id, item in self.device_items.items():
            item.set_class(device_id == self.selected_device_id, "--highlight")
        for device_id, item in self.my_items.items():
            item.set_class(device_id == self.selected_device_id, "--highlight")

    def update_detail(self, device: Device) -> None:
        owner = device.owner or "Unassigned"
        owner_tone = "#5db4ff" if device.owner == CURRENT_USER else "#c9d8ea"
        status_tone = status_color(device.status)
        password = device.password if self.show_password else "*" * max(8, len(device.password))
        detail = (
            f"[bold white]{device.name}[/]\n"
            f"[#88a0ba]{device.id}  •  {device.domain}  •  {device.device_type}[/]\n\n"
            f"[bold #5db4ff]Conn[/]  SSH {device.ssh_ip}  |  Telnet {device.telnet_ip}\n"
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
            return
        self.selected_device_id = device.id
        self.sync_selection_styles()
        self.update_detail(device)

    def action_focus_filter(self) -> None:
        self.query_one("#filter-input", Input).focus()

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
        if not self.selected_device_id:
            return
        if shutil.which("ssh") is None:
            self.notify("ssh command not found", severity="error", timeout=3)
            return

        device = self.get_selected_device()
        self.run_external_command(["ssh", f"{device.username}@{device.ssh_ip}"])
        self.notify(f"SSH closed: {device.name}", timeout=2)

    def action_ssh_connect_external(self) -> None:
        if not self.selected_device_id:
            return
        if shutil.which("ssh") is None:
            self.notify("ssh command not found", severity="error", timeout=3)
            return

        device = self.get_selected_device()
        launched = self.launch_detached_terminal(
            title=device.name,
            command=f"ssh {device.username}@{device.ssh_ip}",
        )
        if launched:
            self.notify(f"Opened SSH window: {device.name}", timeout=2)
        else:
            self.notify("No terminal launcher found", severity="error", timeout=3)

    def action_telnet_connect(self) -> None:
        if not self.selected_device_id:
            return
        if shutil.which("telnet") is None:
            self.notify("telnet command not found", severity="error", timeout=3)
            return

        device = self.get_selected_device()
        self.run_external_command(["telnet", device.telnet_ip])
        self.notify(f"Telnet closed: {device.name}", timeout=2)

    def action_telnet_connect_external(self) -> None:
        if not self.selected_device_id:
            return
        if shutil.which("telnet") is None:
            self.notify("telnet command not found", severity="error", timeout=3)
            return

        device = self.get_selected_device()
        launched = self.launch_detached_terminal(
            title=device.name,
            command=f"telnet {device.telnet_ip}",
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
        if self.selected_device_id:
            self.update_detail(self.get_selected_device())

    def toggle_occupancy_for_device(self, device: Device) -> None:
        if device.owner == CURRENT_USER and device.status == STATUS_OCCUPIED:
            device.owner = None
            device.status = STATUS_IDLE
            message = f"Released {device.name}"
        elif device.owner is None and device.status == STATUS_IDLE:
            device.owner = CURRENT_USER
            device.status = STATUS_OCCUPIED
            message = f"Claimed {device.name}"
        else:
            message = f"{device.name} is {device.status}"

        self.refresh_filtered_view()
        self.notify(message, timeout=2)

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

        self.toggle_occupancy_for_device(self.get_selected_device())


def main() -> None:
    DeviceDashboard().run()


if __name__ == "__main__":
    main()

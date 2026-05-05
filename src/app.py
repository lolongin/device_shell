from __future__ import annotations

import shutil
import subprocess

from rich.text import Text
from textual import on
from textual.app import App, ComposeResult
from textual.containers import Container, Horizontal, HorizontalScroll, Vertical
from textual.reactive import reactive
from textual.widgets import Button, Footer, Header, Input, Label, ListItem, ListView, Static

from data import CURRENT_USER, Device, sample_devices


ALL_DOMAINS = "\u5168\u90e8\u9886\u57df"
ALL_STATUS = "\u5168\u90e8\u72b6\u6001"
ALL_CPUS = "\u5168\u90e8CPU"
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
    height: 1fr;
    border: tall #24415f;
    background: #0d1726;
    padding: 1;
}

.panel-title {
    color: #8ac6ff;
    text-style: bold;
    margin-bottom: 1;
}

.section-copy {
    color: #7d93ad;
    margin-bottom: 1;
}

#stats-row {
    height: auto;
    margin-bottom: 1;
}

#stats-strip {
    color: #9cb4ce;
    background: #091422;
    border: round #16314d;
    padding: 0 1;
}

#filter-input {
    width: 1fr;
    margin-bottom: 1;
    background: #08111f;
    color: #e8f0ff;
    border: round #16314d;
}

#filter-input:focus {
    border: round #5db4ff;
}

#filter-ribbon {
    height: 3;
    margin-bottom: 1;
    scrollbar-size-horizontal: 1;
    scrollbar-background: #0d1726;
    scrollbar-color: #355f8c;
    scrollbar-color-hover: #5db4ff;
}

#filter-ribbon-inner {
    width: auto;
    height: auto;
}

.chip-section {
    width: auto;
    margin-right: 2;
}

.chip-group-title {
    width: auto;
    min-width: 5;
    color: #7d93ad;
    padding: 1 1 0 0;
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
    border: round #16314d;
}

ListView:focus {
    border: round #5db4ff;
}

ListItem {
    padding: 0 1;
    margin: 0 0 1 0;
    background: #0e1b2c;
    color: #d9e8ff;
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
        STATUS_OCCUPIED: "#35d07f",
        STATUS_IDLE: "#5db4ff",
        STATUS_PIPELINE: "#ffb65c",
        STATUS_OTHER: "#b88cff",
    }
    return palette.get(status, "#88a0ba")


class DeviceListItem(ListItem):
    def __init__(self, device: Device, sequence: int, emphasis: bool = False) -> None:
        self.device = device
        self.sequence = sequence
        super().__init__(Label(self.render_text(), markup=True))
        if emphasis:
            self.add_class("--highlight")

    def render_text(self) -> str:
        color = status_color(self.device.status)
        return (
            f"[#7d93ad]{self.sequence:04d}[/] [b]{self.device.name}[/b]\n"
            f"[#88a0ba]{self.device.domain}[/]  "
            f"[#5db4ff]CPU {self.device.cpu}[/]  "
            f"[{color}]{self.device.status}[/]"
        )


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
    filter_domain = reactive(ALL_DOMAINS)
    filter_status = reactive(ALL_STATUS)
    filter_cpu = reactive(ALL_CPUS)
    show_password = reactive(False)

    def __init__(self) -> None:
        super().__init__()
        self.devices = sample_devices()
        self.search_index = {
            device.id: " ".join(
                [
                    device.id,
                    device.name,
                    device.domain,
                    device.device_type,
                    device.cpu,
                    device.status,
                    device.vendor,
                    device.model,
                    device.site,
                    device.rack,
                ]
            ).lower()
            for device in self.devices
        }
        self.visible_devices: list[Device] = self.devices[:]
        self.visible_owned_devices: list[Device] = []
        self.device_items: dict[str, DeviceListItem] = {}
        self.my_items: dict[str, DeviceListItem] = {}
        self.domain_button_ids: dict[str, str] = {}
        self.status_button_ids: dict[str, str] = {}
        self.cpu_button_ids: dict[str, str] = {}

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="shell"):
            with Vertical(id="left-pane"):
                with Container(classes="panel"):
                    yield Label("Device List", classes="panel-title")
                    yield Static("\u8bbe\u5907 / \u9886\u57df / CPU / \u72b6\u6001", classes="section-copy")
                    with Horizontal(id="stats-row"):
                        yield Static(id="stats-strip")
                    yield Input(
                        placeholder="\u641c\u7d22\u8bbe\u5907\u540d / \u9886\u57df / CPU / \u72b6\u6001",
                        id="filter-input",
                    )
                    with HorizontalScroll(id="filter-ribbon"):
                        with Horizontal(id="filter-ribbon-inner"):
                            yield from self.compose_domain_chips()
                            yield from self.compose_status_chips()
                            yield from self.compose_cpu_chips()
                    yield ListView(id="device-list")
                with Container(classes="panel"):
                    yield Label("My Occupancy", classes="panel-title")
                    yield Static(f"Current User: {CURRENT_USER}", classes="section-copy")
                    yield ListView(id="my-list")
            with Container(id="right-pane", classes="panel"):
                yield Label("Device Detail", classes="panel-title")
                yield Static("\u8fde\u63a5 / \u8d44\u4ea7 / \u4f4d\u7f6e", classes="section-copy")
                yield Static(id="detail-card")
        yield Footer()

    def compose_domain_chips(self) -> ComposeResult:
        with Horizontal(classes="chip-section"):
            yield Static("\u9886\u57df", classes="chip-group-title")
            for index, domain in enumerate([ALL_DOMAINS, *self.domain_values()]):
                button_id = f"domain_chip_{index}"
                self.domain_button_ids[domain] = button_id
                yield Button(domain, id=button_id, classes="filter-chip")

    def compose_status_chips(self) -> ComposeResult:
        with Horizontal(classes="chip-section"):
            yield Static("\u72b6\u6001", classes="chip-group-title")
            for index, status in enumerate([ALL_STATUS, *STATUS_ORDER]):
                button_id = f"status_chip_{index}"
                self.status_button_ids[status] = button_id
                yield Button(status, id=button_id, classes="filter-chip")

    def compose_cpu_chips(self) -> ComposeResult:
        with Horizontal(classes="chip-section"):
            yield Static("CPU", classes="chip-group-title")
            for index, cpu in enumerate([ALL_CPUS, *self.cpu_values()]):
                button_id = f"cpu_chip_{index}"
                self.cpu_button_ids[cpu] = button_id
                yield Button(cpu, id=button_id, classes="filter-chip")

    def on_mount(self) -> None:
        self.selected_device_id = self.devices[0].id
        self.compute_visible_devices()
        self.refresh_filter_chips()
        self.refresh_lists()
        self.ensure_valid_selection()
        self.update_detail(self.get_selected_device())
        self.query_one("#device-list", ListView).focus()

    def domain_values(self) -> list[str]:
        return sorted({device.domain for device in self.devices})

    def cpu_values(self) -> list[str]:
        return sorted({device.cpu for device in self.devices})

    def compute_visible_devices(self) -> None:
        keyword = self.filter_text.strip().lower()
        filtered: list[Device] = []
        for device in self.devices:
            if self.filter_domain != ALL_DOMAINS and device.domain != self.filter_domain:
                continue
            if self.filter_status != ALL_STATUS and device.status != self.filter_status:
                continue
            if self.filter_cpu != ALL_CPUS and device.cpu != self.filter_cpu:
                continue
            if keyword and keyword not in self.search_index[device.id]:
                continue
            filtered.append(device)

        self.visible_devices = filtered
        self.visible_owned_devices = [
            device for device in filtered if device.owner == CURRENT_USER
        ]

    def refresh_filter_chips(self) -> None:
        for domain, button_id in self.domain_button_ids.items():
            self.query_one(f"#{button_id}", Button).set_class(domain == self.filter_domain, "-active")
        for status, button_id in self.status_button_ids.items():
            self.query_one(f"#{button_id}", Button).set_class(status == self.filter_status, "-active")
        for cpu, button_id in self.cpu_button_ids.items():
            self.query_one(f"#{button_id}", Button).set_class(cpu == self.filter_cpu, "-active")
        self.scroll_active_chip_into_view()

    def active_chip_id(self) -> str | None:
        if self.filter_cpu != ALL_CPUS:
            return self.cpu_button_ids.get(self.filter_cpu)
        if self.filter_status != ALL_STATUS:
            return self.status_button_ids.get(self.filter_status)
        return self.domain_button_ids.get(self.filter_domain)

    def scroll_active_chip_into_view(self) -> None:
        button_id = self.active_chip_id()
        if not button_id:
            return
        ribbon = self.query_one("#filter-ribbon", HorizontalScroll)
        ribbon.scroll_to_widget(
            self.query_one(f"#{button_id}", Button),
            animate=False,
            center=False,
        )

    def update_stats(self) -> None:
        counts = {status: 0 for status in STATUS_ORDER}
        for device in self.visible_devices:
            if device.status in counts:
                counts[device.status] += 1

        stats_text = (
            f"[bold #8ac6ff]\u603b\u6570[/] {len(self.visible_devices)}    "
            f"[bold #35d07f]\u5df2\u5360\u7528[/] {counts[STATUS_OCCUPIED]}    "
            f"[bold #5db4ff]\u7a7a\u95f2[/] {counts[STATUS_IDLE]}    "
            f"[bold #ffb65c]\u6d41\u6c34\u7ebf[/] {counts[STATUS_PIPELINE]}    "
            f"[bold #b88cff]\u5176\u4ed6[/] {counts[STATUS_OTHER]}"
        )
        self.query_one("#stats-strip", Static).update(Text.from_markup(stats_text))

    def refresh_lists(self) -> None:
        device_list = self.query_one("#device-list", ListView)
        my_list = self.query_one("#my-list", ListView)

        self.update_stats()
        device_list.clear()
        my_list.clear()
        self.device_items.clear()
        self.my_items.clear()

        for index, device in enumerate(self.visible_devices, start=1):
            item = DeviceListItem(device, sequence=index, emphasis=device.id == self.selected_device_id)
            self.device_items[device.id] = item
            device_list.append(item)

        for index, device in enumerate(self.visible_owned_devices, start=1):
            item = DeviceListItem(device, sequence=index, emphasis=device.id == self.selected_device_id)
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
        self.refresh_filter_chips()
        self.refresh_lists()
        self.ensure_valid_selection()
        if self.selected_device_id:
            self.update_detail(self.get_selected_device())

    @on(Input.Changed, "#filter-input")
    def handle_filter_changed(self, event: Input.Changed) -> None:
        self.filter_text = event.value
        self.refresh_filtered_view()

    @on(Button.Pressed, ".filter-chip")
    def handle_filter_chip_pressed(self, event: Button.Pressed) -> None:
        button_id = event.button.id or ""
        for domain, domain_button_id in self.domain_button_ids.items():
            if button_id == domain_button_id:
                self.filter_domain = domain
                self.refresh_filtered_view()
                return
        for status, status_button_id in self.status_button_ids.items():
            if button_id == status_button_id:
                self.filter_status = status
                self.refresh_filtered_view()
                return
        for cpu, cpu_button_id in self.cpu_button_ids.items():
            if button_id == cpu_button_id:
                self.filter_cpu = cpu
                self.refresh_filtered_view()
                return

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

        device = self.get_selected_device()
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


def main() -> None:
    DeviceDashboard().run()


if __name__ == "__main__":
    main()

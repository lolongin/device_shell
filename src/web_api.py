from __future__ import annotations

import argparse
import json
import os
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import unquote, urlparse

try:
    from .data import (
        CURRENT_USER,
        STATUS_IDLE,
        STATUS_OCCUPIED,
        STATUS_OTHER,
        STATUS_PIPELINE,
        Device,
        large_sample_devices,
        sample_devices,
    )
except ImportError:
    from data import (
        CURRENT_USER,
        STATUS_IDLE,
        STATUS_OCCUPIED,
        STATUS_OTHER,
        STATUS_PIPELINE,
        Device,
        large_sample_devices,
        sample_devices,
    )


STATUS_TO_CODE = {
    STATUS_OCCUPIED: "occupied",
    STATUS_IDLE: "idle",
    STATUS_PIPELINE: "pipeline",
    STATUS_OTHER: "other",
}


HTML_PAGE = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Device Service</title>
  <style>
    :root {
      --bg: #07111d;
      --panel: #0d1726;
      --line: #1d3550;
      --text: #e7efff;
      --muted: #8aa3bf;
      --accent: #5db4ff;
      --ok: #35d07f;
      --warn: #f4c861;
      --other: #b88cff;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      font-family: "Segoe UI", "Noto Sans", sans-serif;
      background:
        radial-gradient(circle at top right, rgba(93, 180, 255, 0.16), transparent 30%),
        linear-gradient(180deg, #091422, var(--bg));
      color: var(--text);
    }
    .shell {
      max-width: 1200px;
      margin: 0 auto;
      padding: 32px 20px 48px;
    }
    .hero {
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: end;
      margin-bottom: 24px;
    }
    .hero h1 {
      margin: 0;
      font-size: 32px;
      letter-spacing: 0.03em;
    }
    .hero p {
      margin: 8px 0 0;
      color: var(--muted);
      max-width: 680px;
    }
    .meta {
      text-align: right;
      color: var(--muted);
    }
    .grid {
      display: grid;
      grid-template-columns: repeat(5, minmax(0, 1fr));
      gap: 12px;
      margin-bottom: 16px;
    }
    .stat, .panel {
      background: rgba(13, 23, 38, 0.92);
      border: 1px solid var(--line);
      border-radius: 16px;
      backdrop-filter: blur(8px);
    }
    .stat {
      padding: 16px;
    }
    .stat label {
      display: block;
      color: var(--muted);
      margin-bottom: 6px;
      font-size: 13px;
    }
    .stat strong {
      font-size: 28px;
    }
    .panel {
      padding: 18px;
    }
    .panel h2 {
      margin: 0 0 12px;
      font-size: 18px;
    }
    table {
      width: 100%;
      border-collapse: collapse;
    }
    th, td {
      padding: 12px 10px;
      border-bottom: 1px solid rgba(138, 163, 191, 0.16);
      font-size: 14px;
      text-align: left;
      vertical-align: top;
    }
    th {
      color: var(--muted);
      font-weight: 600;
    }
    .badge {
      display: inline-flex;
      padding: 3px 8px;
      border-radius: 999px;
      border: 1px solid var(--line);
      background: rgba(16, 29, 46, 0.9);
      font-size: 12px;
    }
    .status-idle { color: var(--ok); }
    .status-occupied { color: var(--warn); }
    .status-pipeline { color: #ffb65c; }
    .status-other { color: var(--other); }
    .actions {
      display: flex;
      gap: 8px;
      flex-wrap: wrap;
    }
    button {
      border: 1px solid var(--line);
      background: #122339;
      color: var(--text);
      border-radius: 999px;
      padding: 8px 12px;
      cursor: pointer;
    }
    button:hover {
      border-color: var(--accent);
    }
    button:disabled {
      opacity: 0.45;
      cursor: default;
    }
    .hint {
      color: var(--muted);
      margin: 0 0 12px;
      font-size: 13px;
    }
    .flash {
      min-height: 24px;
      color: var(--accent);
      margin-bottom: 10px;
    }
    @media (max-width: 900px) {
      .hero {
        flex-direction: column;
        align-items: start;
      }
      .meta {
        text-align: left;
      }
      .grid {
        grid-template-columns: repeat(2, minmax(0, 1fr));
      }
      table, thead, tbody, tr, th, td {
        display: block;
      }
      thead {
        display: none;
      }
      tr {
        border-bottom: 1px solid rgba(138, 163, 191, 0.16);
        padding: 12px 0;
      }
      td {
        border-bottom: none;
        padding: 6px 0;
      }
      td::before {
        content: attr(data-label);
        display: block;
        color: var(--muted);
        font-size: 12px;
        margin-bottom: 3px;
      }
    }
  </style>
</head>
<body>
  <div class="shell">
    <section class="hero">
      <div>
        <h1>Device Control Web</h1>
        <p>Local browser page backed by real HTTP APIs. The TUI can poll this service, and the page itself can claim or release devices.</p>
      </div>
      <div class="meta">
        <div id="current-user">Current User: --</div>
        <div id="last-sync">Last Sync: --</div>
      </div>
    </section>

    <section class="grid">
      <div class="stat"><label>Total</label><strong id="stat-total">0</strong></div>
      <div class="stat"><label>Occupied</label><strong id="stat-occupied">0</strong></div>
      <div class="stat"><label>Idle</label><strong id="stat-idle">0</strong></div>
      <div class="stat"><label>Pipeline</label><strong id="stat-pipeline">0</strong></div>
      <div class="stat"><label>Other</label><strong id="stat-other">0</strong></div>
    </section>

    <section class="panel">
      <h2>Devices</h2>
      <p class="hint">APIs: <code>GET /api/me</code>, <code>GET /api/devices</code>, <code>GET /api/events</code>, <code>POST /api/devices/&lt;id&gt;/toggle</code>, <code>POST /api/devices/&lt;id&gt;/claim</code>, <code>POST /api/devices/&lt;id&gt;/release</code>.</p>
      <div id="flash" class="flash"></div>
      <table>
        <thead>
          <tr>
            <th>ID</th>
            <th>Device</th>
            <th>Domain</th>
            <th>CPU</th>
            <th>Status</th>
            <th>Owner</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody id="device-rows"></tbody>
      </table>
    </section>
  </div>

  <script>
    const flashNode = document.getElementById("flash");
    const rowsNode = document.getElementById("device-rows");
    let currentUser = "";
    let currentRevision = 0;

    const statusClass = {
      idle: "status-idle",
      occupied: "status-occupied",
      pipeline: "status-pipeline",
      other: "status-other",
    };

    function setFlash(message, isError = false) {
      flashNode.textContent = message;
      flashNode.style.color = isError ? "#ff8a80" : "#5db4ff";
    }

    function countStatuses(devices) {
      const counts = { occupied: 0, idle: 0, pipeline: 0, other: 0 };
      devices.forEach((device) => {
        counts[device.status_code] = (counts[device.status_code] || 0) + 1;
      });
      return counts;
    }

    async function fetchJson(url, options = {}) {
      const response = await fetch(url, options);
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.message || payload.error || "Request failed");
      }
      return payload;
    }

    function renderRows(devices) {
      rowsNode.innerHTML = devices.map((device) => {
        const owner = device.occupancy.owner || "-";
        const canClaim = device.status_code === "idle" && !device.occupancy.owner;
        const canRelease = device.occupancy.owner === currentUser;
        const canToggle = canClaim || canRelease;
        const toggleLabel = canRelease ? "Release" : "Claim";
        return `
          <tr>
            <td data-label="ID">${device.device_id}</td>
            <td data-label="Device">${device.display_name}</td>
            <td data-label="Domain">${device.domain_name}</td>
            <td data-label="CPU">${device.cpu_arch}</td>
            <td data-label="Status"><span class="badge ${statusClass[device.status_code] || ""}">${device.status_label}</span></td>
            <td data-label="Owner">${owner}</td>
            <td data-label="Actions">
              <div class="actions">
                <button data-action="toggle" data-id="${device.device_id}" ${canToggle ? "" : "disabled"}>${toggleLabel}</button>
                <button data-action="claim" data-id="${device.device_id}" ${canClaim ? "" : "disabled"}>Claim</button>
                <button data-action="release" data-id="${device.device_id}" ${canRelease ? "" : "disabled"}>Release</button>
              </div>
            </td>
          </tr>
        `;
      }).join("");
    }

    async function refreshPage() {
      try {
        const [me, devicePayload] = await Promise.all([
          fetchJson("/api/me"),
          fetchJson("/api/devices"),
        ]);
        currentUser = me.current_user;
        currentRevision = Number(devicePayload.revision || currentRevision || 0);
        document.getElementById("current-user").textContent = `Current User: ${currentUser}`;
        document.getElementById("last-sync").textContent = `Last Sync: ${new Date().toLocaleTimeString()}`;
        const devices = devicePayload.devices;
        const counts = countStatuses(devices);
        document.getElementById("stat-total").textContent = String(devices.length);
        document.getElementById("stat-occupied").textContent = String(counts.occupied || 0);
        document.getElementById("stat-idle").textContent = String(counts.idle || 0);
        document.getElementById("stat-pipeline").textContent = String(counts.pipeline || 0);
        document.getElementById("stat-other").textContent = String(counts.other || 0);
        renderRows(devices);
      } catch (error) {
        setFlash(error.message, true);
      }
    }

    async function watchUpdates() {
      while (true) {
        try {
          const payload = await fetchJson(`/api/events?since=${encodeURIComponent(currentRevision)}&timeout=25`);
          currentRevision = Number(payload.revision || currentRevision || 0);
          if (payload.changed) {
            await refreshPage();
          }
        } catch (error) {
          setFlash(error.message, true);
          await new Promise((resolve) => window.setTimeout(resolve, 2000));
        }
      }
    }

    rowsNode.addEventListener("click", async (event) => {
      const button = event.target.closest("button");
      if (!button) {
        return;
      }
      const action = button.dataset.action;
      const deviceId = button.dataset.id;
      try {
        const payload = await fetchJson(`/api/devices/${encodeURIComponent(deviceId)}/${action}`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ user: currentUser }),
        });
        setFlash(payload.message || `${action} ok`);
        await refreshPage();
      } catch (error) {
        setFlash(error.message, true);
        await refreshPage();
      }
    });

    refreshPage();
    watchUpdates();
    setInterval(refreshPage, 30000);
  </script>
</body>
</html>
"""


class DeviceServiceState:
    def __init__(self, current_user: str) -> None:
        self.current_user = current_user
        try:
            sample_count = int(os.getenv("DEVICE_TUI_SAMPLE_DEVICE_COUNT", "0") or "0")
        except ValueError:
            sample_count = 0
        self._devices = large_sample_devices(sample_count) if sample_count > 0 else sample_devices()
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)
        self._revision = 1

    def get_current_user(self) -> str:
        return self.current_user

    def list_devices(self) -> list[dict[str, Any]]:
        with self._lock:
            return [device_to_payload(device, self.current_user) for device in self._devices]

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "revision": self._revision,
                "devices": [device_to_payload(device, self.current_user) for device in self._devices],
            }

    def my_occupancy_snapshot(self) -> dict[str, Any]:
        with self._lock:
            devices = [device for device in self._devices if device.owner == self.current_user]
            return {
                "current_user": self.current_user,
                "revision": self._revision,
                "device_ids": [device.id for device in devices],
                "devices": [device_to_payload(device, self.current_user) for device in devices],
            }

    def current_revision(self) -> int:
        with self._lock:
            return self._revision

    def wait_for_update(self, since_revision: int, timeout_seconds: float) -> dict[str, Any]:
        with self._condition:
            if self._revision <= since_revision:
                self._condition.wait(timeout=max(timeout_seconds, 0.0))
            changed = self._revision > since_revision
            return {"changed": changed, "revision": self._revision}

    def claim_device(self, device_id: str, user: str) -> dict[str, Any]:
        with self._condition:
            device = self._find_device(device_id)
            if device.status != STATUS_IDLE or device.owner is not None:
                raise ConflictError(f"{device.name} is {device.status}")
            device.status = STATUS_OCCUPIED
            device.owner = user
            self._revision += 1
            self._condition.notify_all()
            return {
                "message": f"Claimed {device.name}",
                "revision": self._revision,
                "device": device_to_payload(device, self.current_user),
            }

    def toggle_device(self, device_id: str, user: str) -> dict[str, Any]:
        with self._condition:
            device = self._find_device(device_id)
            if device.owner == user:
                device.status = STATUS_IDLE
                device.owner = None
                message = f"Released {device.name}"
            elif device.status == STATUS_IDLE and device.owner is None:
                device.status = STATUS_OCCUPIED
                device.owner = user
                message = f"Claimed {device.name}"
            else:
                raise ConflictError(f"{device.name} is {device.status}")

            self._revision += 1
            self._condition.notify_all()
            return {
                "message": message,
                "revision": self._revision,
                "device": device_to_payload(device, self.current_user),
            }

    def release_device(self, device_id: str, user: str) -> dict[str, Any]:
        with self._condition:
            device = self._find_device(device_id)
            if device.owner != user:
                raise ConflictError(f"{device.name} is {device.status}")
            device.status = STATUS_IDLE
            device.owner = None
            self._revision += 1
            self._condition.notify_all()
            return {
                "message": f"Released {device.name}",
                "revision": self._revision,
                "device": device_to_payload(device, self.current_user),
            }

    def power_off_device(self, device_id: str, user: str) -> dict[str, Any]:
        with self._condition:
            device = self._find_device(device_id)
            if device.owner != user:
                raise ConflictError(f"{device.name} is not occupied by {user}")
            if not device.supports_power_off:
                raise ConflictError(f"{device.name} does not support power off")
            self._revision += 1
            self._condition.notify_all()
            return {
                "message": f"Powered off {device.name}",
                "revision": self._revision,
                "device": device_to_payload(device, self.current_user),
            }

    def _find_device(self, device_id: str) -> Device:
        for device in self._devices:
            if device.id == device_id:
                return device
        raise NotFoundError(f"Unknown device id: {device_id}")


class WebApiError(Exception):
    status = HTTPStatus.BAD_REQUEST


class NotFoundError(WebApiError):
    status = HTTPStatus.NOT_FOUND


class ConflictError(WebApiError):
    status = HTTPStatus.CONFLICT


def device_to_payload(device: Device, current_user: str = "") -> dict[str, Any]:
    can_view_serial = bool(current_user and device.owner == current_user)
    return {
        "device_id": device.id,
        "display_name": device.name,
        "domain_name": device.domain,
        "kind": device.device_type,
        "cpu_arch": device.cpu,
        "status_code": STATUS_TO_CODE.get(device.status, "other"),
        "status_label": device.status,
        "occupancy": {"owner": device.owner},
        "capabilities": {
            "power_off": device.supports_power_off,
        },
        "power": {
            "supports_power_off": device.supports_power_off,
        },
        "connection": {
            "ssh_host": device.ssh_ip,
            "ssh_port": device.ssh_port,
            "telnet_host": device.telnet_ip,
            "telnet_port": device.telnet_port,
            "serial_host": device.serial_ip if can_view_serial else "",
            "serial_port": device.serial_port if can_view_serial else 0,
            "ssh_username": device.ssh_username or device.username,
            "ssh_password": device.ssh_password or device.password,
            "telnet_username": device.username,
            "telnet_password": device.password,
            "serial_username": device.serial_username or device.username,
            "serial_password": device.serial_password or device.password,
            "username": device.username,
            "password": device.password,
        },
        "asset": {
            "vendor": device.vendor,
            "model": device.model,
            "version": device.version,
            "site": device.site,
            "rack": device.rack,
        },
        "notes": device.notes,
    }


def create_request_handler(state: DeviceServiceState) -> type[BaseHTTPRequestHandler]:
    class DeviceRequestHandler(BaseHTTPRequestHandler):
        server_version = "DeviceService/0.1"

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/":
                self._write_html(HTML_PAGE)
                return
            if parsed.path == "/api/health":
                self._write_json(HTTPStatus.OK, {"status": "ok"})
                return
            if parsed.path == "/api/me":
                self._write_json(HTTPStatus.OK, {"current_user": state.get_current_user()})
                return
            if parsed.path == "/api/devices":
                self._write_json(HTTPStatus.OK, state.snapshot())
                return
            if parsed.path == "/api/my-occupancy":
                self._write_json(HTTPStatus.OK, state.my_occupancy_snapshot())
                return
            if parsed.path == "/api/events":
                try:
                    since = int(self._query_value(parsed.query, "since", "0"))
                    timeout = float(self._query_value(parsed.query, "timeout", "25"))
                except ValueError:
                    self._write_error(WebApiError("Invalid event query parameters"))
                    return
                self._write_json(HTTPStatus.OK, state.wait_for_update(since, timeout))
                return
            self._write_error(NotFoundError("Route not found"))

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            segments = [segment for segment in parsed.path.split("/") if segment]
            if len(segments) != 4 or segments[0] != "api" or segments[1] != "devices":
                self._write_error(NotFoundError("Route not found"))
                return

            device_id = unquote(segments[2])
            action = segments[3]
            try:
                payload = self._read_json()
                user = str(payload.get("user") or state.get_current_user())
                if action == "toggle":
                    response = state.toggle_device(device_id, user)
                elif action == "claim":
                    response = state.claim_device(device_id, user)
                elif action == "release":
                    response = state.release_device(device_id, user)
                elif action in {"power-off", "power_off"}:
                    response = state.power_off_device(device_id, user)
                else:
                    raise NotFoundError("Route not found")
            except WebApiError as exc:
                self._write_error(exc)
                return
            except json.JSONDecodeError:
                self._write_error(WebApiError("Invalid JSON body"))
                return

            self._write_json(HTTPStatus.OK, response)

        def log_message(self, format: str, *args: object) -> None:
            return

        def _read_json(self) -> dict[str, Any]:
            content_length = int(self.headers.get("Content-Length", "0") or "0")
            if content_length <= 0:
                return {}
            raw = self.rfile.read(content_length).decode("utf-8")
            data = json.loads(raw)
            return data if isinstance(data, dict) else {}

        def _query_value(self, query: str, key: str, default: str) -> str:
            for chunk in query.split("&"):
                if not chunk:
                    continue
                name, _, value = chunk.partition("=")
                if name == key:
                    return unquote(value)
            return default

        def _write_html(self, content: str) -> None:
            body = content.encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _write_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _write_error(self, exc: Exception) -> None:
            status = exc.status if isinstance(exc, WebApiError) else HTTPStatus.INTERNAL_SERVER_ERROR
            message = str(exc) or status.phrase
            self._write_json(status, {"error": status.phrase, "message": message})

    return DeviceRequestHandler


def create_server(host: str, port: int, current_user: str) -> ThreadingHTTPServer:
    state = DeviceServiceState(current_user=current_user)
    handler = create_request_handler(state)
    return ThreadingHTTPServer((host, port), handler)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the local device web API and browser page.")
    parser.add_argument("--host", default=os.getenv("DEVICE_TUI_WEB_HOST", "127.0.0.1"))
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.getenv("DEVICE_TUI_WEB_PORT", "8765")),
    )
    parser.add_argument(
        "--user",
        default=os.getenv("DEVICE_TUI_CURRENT_USER", CURRENT_USER),
        help="Current user shown by the service and used by the built-in web page.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    server = create_server(args.host, args.port, args.user)
    print(f"Device web service running at http://{args.host}:{args.port}")
    print(f"Current user: {args.user}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()

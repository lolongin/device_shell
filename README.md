# Network Device TUI

一个用于管理网络设备的现代化终端看板。

- 左上：设备列表，显示序号、领域、设备名、CPU 型号、状态
- 左下：我的占用，显示当前由我负责的设备
- 右侧：设备详情，显示 SSH IP、Telnet IP、账号密码及基础资产信息

## Install

```bash
pip install -e .
```

or

```bash
pip install textual
```

## Run

```bash
python src/app.py
```

or after install

```bash
device-tui
```

## Web API Mode

Default mode uses the in-memory sample dataset.

To run the local browser page and HTTP APIs:

```bash
python src/web_api.py --host 127.0.0.1 --port 8765
```

After installation you can also run:

```bash
device-tui-web
```

Open [http://127.0.0.1:8765](http://127.0.0.1:8765) in a browser to view the page.

To make the TUI read and write through the HTTP APIs instead of the local sample repository:

```bash
set DEVICE_TUI_DATA_SOURCE=api
set DEVICE_TUI_API_BASE_URL=http://127.0.0.1:8765
set DEVICE_TUI_REFRESH_SECONDS=30
python src/app.py
```

In API mode, the web page and TUI use the `/api/events` long-poll endpoint for near-real-time state sync, with periodic refresh kept as a fallback.
The TUI does not decide claim vs release from local state in API mode; it sends a backend-authoritative `toggle` request and then refreshes from the server.

## Mock Huawei Device

You can start a local mock Huawei Telnet device for CLI testing:

```bash
python src/mock_huawei_device.py --host 127.0.0.1 --port 2323
```

After installation you can also run:

```bash
device-tui-mock-huawei
```

Default mock credentials:

- Host: `127.0.0.1`
- Port: `2323`
- Username: `lon`
- Password: `202188`

The right-side `CLI Session` pane in the TUI can connect to this mock device and test:

- Username / password login
- Huawei prompt detection
- `screen-length 0 temporary`
- `display version`
- `display current-configuration`
- `display ip interface brief`
- `system-view`
- `quit` / `return`

## Mock Linux SSH

You can start a local mock Linux SSH backend for workflow testing:

```bash
python src/mock_linux_ssh.py --host 127.0.0.1 --port 2200
```

After installation you can also run:

```bash
device-tui-mock-linux
```

Default mock credentials:

- Host: `127.0.0.1`
- Port: `2200`
- Username: `ops`
- Password: `ops123`

The mock SSH server supports:

- Username / password login
- Normal SSH command execution
- A small in-memory Linux filesystem
- Workflow-friendly commands such as `mkdir -p`, `echo ... > file`, `cat`, `ls`, `pwd`, `whoami`

Recommended pairing for local dual-channel testing:

- Device Telnet: `python src/mock_huawei_device.py --host 127.0.0.1 --port 2323`
- Linux SSH: `python src/mock_linux_ssh.py --host 127.0.0.1 --port 2200`

## Dual-Channel CLI

The right-side `CLI Session` pane now supports two execution channels:

- `device`: Telnet login to the selected Huawei device
- `linux`: SSH login to a backend Linux host using `asyncssh`

Routing rules:

- Normal commands are sent directly to the connected `device` channel
- Commands starting with `/` are treated as local workflows and run step-by-step across `device` and `linux`

Built-in workflow stubs:

- `/collect_log`
- `/change_cc <value>`

Current implementation notes:

- The device target still follows the selected device in the list
- Device username / password can be overridden in the TUI before connecting
- Linux host / port / username / password are entered separately in the TUI
- Workflow output, Linux output, and device output are merged into one log window with source tags

Optional environment variables:

- `DEVICE_TUI_CURRENT_USER`: override the current user used by the sample mode and web service
- `DEVICE_TUI_API_BASE_URL`: base URL for the HTTP API
- `DEVICE_TUI_API_TIMEOUT_SECONDS`: HTTP timeout for API requests
- `DEVICE_TUI_REFRESH_SECONDS`: polling interval used by the API-backed repository

## Dashboard

设备列表上方增加了运维统计条，统计当前筛选结果中的：

- Total
- Online
- Maintenance
- Alert

统计条会随着关键字、领域、状态筛选实时刷新。

## Combined Filter

顶部支持组合筛选，三种条件可以同时生效：

- 关键字输入
- 领域下拉
- 状态下拉

关键字会匹配这些字段：

- 设备名
- 领域
- CPU 型号
- 状态
- 设备 ID
- 厂商
- 型号
- 站点

## Keys

- `Up / Down`: move in current list
- `Tab`: switch focus
- `/`: focus keyword filter
- `Enter`: inspect selected device
- `o`: claim or release current device
- `q`: quit

## Sample Domains

- `RTN`
- `交企`
- `路由器`
- `XTN`

## Note

示例数据中的账号和密码是演示用途的静态样例。真实环境不建议在本地明文保存密码，建议改成脱敏显示或接入加密存储。

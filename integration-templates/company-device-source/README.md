# Ready-to-use Company Device Source

这是一个开箱即用、可以整体复制到内部代码仓的 Device TUI 插件：

- 已注册 `device_tui.device_sources` Entry Point。
- 已实现账号、密码、CID 登录状态。
- 已实现设备列表、我的占用、占用、释放、切换和下电。
- 已实现版本号和长轮询更新接口。
- 自带两台演示设备，安装后不连接任何内部网站也能完整操作。
- 以后只替换一个网页 API 工厂，插件和仓库代码不需要改。

## 现在直接运行

当前环境如果装有 `device-tui-internal-source`，先卸载，避免两个包同时注册
`internal-site`：

```powershell
python -m pip uninstall device-tui-internal-source
python -m pip install -e .\integration-templates\company-device-source --no-deps
```

重启 Device TUI：

1. 打开“设置 → 数据来源与插件”。
2. 选择“公司设备平台”，直接点击“验证配置”。
3. 回到设备页，切换来源为“公司设备平台”。
4. 点击账号入口，输入任意非空账号、密码和 CID。
5. 登录后可以看到 `INTERNAL-DEMO-01/02`，并验证占用、释放和下电。

演示实现只使用内存，不访问网络，也不会保存登录密码。是否记住密码和自动登录仍
由 Device TUI 主程序通过系统凭据库管理。

## 适配真实内部网站

有两种接入方式。新项目推荐方式一；如果内部仓已经实现了
`create_repository_from_env()`，可以直接使用方式二，避免重复改造。

### 方式一：实现网页 API 适配器（推荐）

主程序、插件注册和设备仓库都不需要修改。内部代码只实现
`CompanyWebApi`，然后在以下文件中替换工厂：

```text
src/company_device_source/binding.py
```

当前工厂返回演示实现：

```python
def create_company_web_api(context: DeviceSourceContext) -> CompanyWebApi:
    return DemoCompanyWebApi()
```

替换为内部实现：

```python
from internal_device.web_api import InternalCompanyWebApi


def create_company_web_api(context: DeviceSourceContext) -> CompanyWebApi:
    return InternalCompanyWebApi(
        base_url=str(context.config.get("base_url") or ""),
        timeout_seconds=float(context.config.get("timeout_seconds") or 5),
    )
```

内部适配器需要实现
`src/company_device_source/web_api.py::CompanyWebApi`：

```python
class InternalCompanyWebApi:
    def auth_status(self) -> CompanyAuthSession: ...
    def login(self, username: str, password: str, cid: str) -> CompanyAuthSession: ...
    def logout(self) -> None: ...
    def list_devices(self) -> list[CompanyDevice]: ...
    def list_owned_device_ids(self) -> set[str]: ...
    def toggle_device(self, device_id: str, user: str) -> str: ...
    def claim_device(self, device_id: str, user: str) -> str: ...
    def release_device(self, device_id: str, user: str) -> str: ...
    def power_off_device(self, device_id: str, user: str) -> str: ...
    def current_revision(self) -> int: ...
    def wait_for_update(self, since_revision: int, timeout_seconds: float) -> int | None: ...
```

一个典型实现会在对象内部持有网站客户端或 HTTP Session：

```python
class InternalCompanyWebApi:
    def __init__(self, base_url: str, timeout_seconds: float) -> None:
        self._client = ExistingInternalWebClient(base_url, timeout_seconds)
        self._username = ""
        self._cid = ""
        self._authenticated = False
        self._revision = 0

    def login(self, username: str, password: str, cid: str) -> CompanyAuthSession:
        # ExistingInternalWebClient 在内部保存登录响应中的 Cookie。
        self._client.login(username=username, password=password, cid=cid)
        self._username = username
        self._cid = cid
        self._authenticated = True
        return self.auth_status()

    def auth_status(self) -> CompanyAuthSession:
        return CompanyAuthSession(
            configured=bool(self._client.base_url),
            authenticated=self._authenticated,
            username=self._username,
            cid=self._cid,
        )

    def logout(self) -> None:
        self._client.logout()
        self._client.clear_cookies()
        self._authenticated = False

    def list_devices(self) -> list[CompanyDevice]:
        rows = self._client.list_devices()
        return [self._map_device(row) for row in rows]
```

Cookie 只应保存在内部客户端的内存 Session 中。Device TUI 负责通过系统凭据库
保存用户选择“记住”的密码；自动登录时会重新调用 `login()`，插件不需要持久化
Cookie、账号或密码。

### 网页字段映射

内部网站返回的数据统一转换成 `CompanyDevice`。常用字段对应关系如下：

| 内部含义 | `CompanyDevice` 字段 | 说明 |
| --- | --- | --- |
| 设备唯一标识 | `id` | 必填且应保持稳定 |
| 显示名称 | `name` | 必填 |
| 设备分类/领域 | `device_type` / `domain` | 用于筛选和展示 |
| 占用状态 | `status_code` | `idle`、`occupied`、`pipeline` 或 `other` |
| 占用人 | `owner` | 无占用时为 `None` |
| SSH 连接 | `ssh_host`、`ssh_port`、`ssh_username` | 没有 SSH 时保持空地址 |
| Telnet 连接 | `telnet_host`、`telnet_port`、`telnet_username` | 没有 Telnet 时保持空地址 |
| 串口服务器 | `serial_host`、`serial_port`、`serial_username` | 对接网络串口服务器 |
| 厂商和型号 | `vendor`、`model` | 可选展示信息 |
| 位置 | `site`、`rack` | 可选展示信息 |
| 扩展字段 | `extra` | 例如 `board_type`、`slot_id` |

示例：

```python
def _map_device(self, row: dict[str, object]) -> CompanyDevice:
    raw_status = str(row.get("state") or "").lower()
    status = {
        "free": "idle",
        "used": "occupied",
        "testing": "pipeline",
    }.get(raw_status, "other")
    return CompanyDevice(
        id=str(row["device_id"]),
        name=str(row.get("device_name") or row["device_id"]),
        device_type=str(row.get("device_type") or "device"),
        status_code=status,
        owner=str(row["owner"]) if row.get("owner") else None,
        telnet_host=str(row.get("management_ip") or ""),
        telnet_port=int(row.get("telnet_port") or 23),
        ssh_host=str(row.get("ssh_ip") or ""),
        ssh_port=int(row.get("ssh_port") or 22),
        extra={"board_type": row.get("board_type", "")},
    )
```

网站业务冲突（例如设备已被他人占用）抛出 `CompanyWebApiConflict`；网络错误、
登录失效、响应格式错误等抛出 `CompanyWebApiError`。不要把响应正文、Cookie、
密码或 Token 放进异常消息。

如果内部网站没有 revision 或长轮询接口，可以在每次设备数据变化时递增本地
revision；`wait_for_update()` 在超时后返回 `None`。主程序仍会按照
`refresh_seconds` 周期刷新设备。

### 方式二：直接复用现有 DeviceRepository

如果内部仓已有：

```python
def create_repository_from_env() -> DeviceRepository:
    ...
```

并且返回对象已经实现 Device TUI 的仓库接口，可以直接修改 `provider.py`：

```python
from internal_device.repository import create_repository_from_env


def create_repository(self, context: DeviceSourceContext):
    del context
    return create_repository_from_env()
```

这种方式会绕过 `binding.py`、`web_api.py` 和 `repository.py` 的字段转换层。返回的
仓库至少需要实现：

```text
current_user
fetch_devices
fetch_owned_device_ids
toggle_device / claim_device / release_device
internal_auth_status
login_internal / logout_internal
current_revision / wait_for_update
```

如果已有仓库只能从环境变量取配置，可以继续保留；更推荐逐步改成接收
`DeviceSourceContext.config`，这样平台地址、超时等配置由主程序统一管理。

### 产品模式配置

网站项目在 Device TUI 根项目的 `desktop/resources/product-profile.json` 中固定数据源：

```json
{
  "mode": "web",
  "source": "internal-site"
}
```

最终用户只会看到网站登录入口，不会看到插件管理或数据源切换。开发调试时可以
暂时使用：

```json
{
  "mode": "universal",
  "source": ""
}
```

## 目录职责

```text
company_device_source/
├── binding.py      # 唯一替换点：创建真实网页 API
├── web_api.py      # 内部网页 API 接口与标准数据结构
├── demo_api.py     # 当前可直接运行的内存实现
├── repository.py   # 完整 DeviceRepository 适配，不建议修改
└── provider.py     # Entry Point 插件定义，不建议修改
```

插件管理页提供平台地址、超时和刷新周期。普通配置写入 SQLite；以后如需 Token，
在 `CONFIG_FIELDS` 增加 `kind="secret"`，通过
`context.secrets.get("字段名")` 获取，前端不会拿到密钥值。

## 测试

```powershell
Set-Location .\integration-templates\company-device-source
python -m pytest -q
```

接入真实 API 后至少验证：

1. 未登录时设备列表为空且工作区不会载入失败。
2. 账号、密码、CID 登录成功后 Cookie 能用于后续设备请求。
3. 退出登录后 Cookie 被清理，设备列表不再返回内部数据。
4. 设备字段和连接地址映射正确。
5. 占用、释放、切换和下电的业务冲突能显示安全错误。
6. 网站不可达、超时和登录失效时不泄露密码、Cookie 或响应正文。

## 发布版打包

```powershell
$env:DEVICE_TUI_SOURCE_PLUGIN_DISTRIBUTIONS = "company-device-source"
$env:DEVICE_TUI_SOURCE_PLUGIN_MODULES = "company_device_source,internal_device"
Set-Location .\desktop
npm run dist
```

将 `internal_device` 替换成真实网页 API 代码的顶层 Python 包名。不要把真实账号、
密码、Cookie、内部 URL 或 Token 提交到公开仓库。

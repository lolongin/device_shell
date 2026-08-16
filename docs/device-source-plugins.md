# Device Source Plugins

Device-source plugins keep company-specific website integration outside the
generic Device TUI repository. The core application owns source selection,
credential prompts, session safety, Excel import, and presentation. A plugin owns
only website authentication, cookie lifetime, remote calls, and mapping remote
records to the canonical Device TUI repository contract.

## Public contract

A plugin imports the stable `device_tui.plugin_api` and `device_tui.repository_api`
surfaces, exposes a `DeviceSourceDescriptor`, and creates an object implementing
`DeviceRepository`. Plugin API version `1` requires all repository methods,
including authentication status, inventory, occupancy actions, revision, and
update waiting. Unsupported remote operations should raise `RepositoryError`
with a user-safe message.

```python
from device_tui.plugin_api import (
    DeviceSourceContext,
    DeviceSourceDescriptor,
    PluginConfigField,
)


class InternalSourcePlugin:
    descriptor = DeviceSourceDescriptor(
        id="internal-site",
        label="公司设备平台",
        description="从公司设备网站加载设备。",
        icon="globe",
        requires_login=True,
        default_priority=100,
    )

    config_fields = (
        PluginConfigField(
            key="base_url",
            label="平台地址",
            kind="url",
            required=True,
        ),
        PluginConfigField(
            key="api_token",
            label="API Token",
            kind="secret",
        ),
    )

    def create_repository(self, context: DeviceSourceContext):
        return InternalDeviceRepository(
            base_url=str(context.config["base_url"]),
            api_token=context.secrets.get("api_token"),
        )


def create_plugin():
    return InternalSourcePlugin()
```

`InternalDeviceRepository` may use any private SDK or webpage wrapper. It must
return canonical `Device` instances and translate private exceptions to
`RepositoryError` or `RepositoryConflictError`. Passwords should not be included
in returned devices. Login passwords are passed to `login_internal()` only for
the duration of the call; keep the resulting website cookie in plugin memory.

`PluginConfigField` is also the source of truth for the App's configuration
form. Supported kinds are `text`, `url`, `number`, `boolean`, `select`, and
`secret`. Ordinary values are stored as JSON in SQLite. Secret values are never
returned by the backend and are stored under
`device-source-plugin/<plugin-id>/<field-key>` in the operating-system credential
vault.

## Independent package

Register the provider from the internal package rather than changing Device TUI:

```toml
[project]
name = "company-device-source"
version = "1.0.0"
dependencies = ["device-tui>=0.1,<1"]

[project.entry-points."device_tui.device_sources"]
company = "company_device_source.provider:create_plugin"
```

Installing that wheel makes the source appear automatically. Uninstalling it
returns the generic App to its built-in sources. Source IDs are dynamic, so the
internal package does not need to use the legacy `api` ID. A higher
`default_priority` makes the internal source the default when no deployment or
user setting overrides it.

Developers manage installed sources from **设置 → 数据来源与插件** in a
`universal` build. The page shows
the plugin version, publisher, built-in/external origin, enabled state, active
and default badges, initialization errors, and generated configuration form.
External plugins can be enabled or disabled. Saving configuration validates and
rebuilds the repository immediately; changing the active source remains blocked
while terminal sessions are open. “验证配置” calls the optional
`test_connection(context)` hook and otherwise verifies that the repository can
be initialized.

Universal/legacy source-selection precedence is:

1. `DEVICE_TUI_DATA_SOURCE` forces a source for the current deployment.
2. The user's last selected source is restored.
3. `DEVICE_TUI_DEFAULT_DATA_SOURCE` selects the product default.
4. The available plugin with the highest `default_priority` is selected.

Managed plugin configuration takes precedence over legacy environment variables.
Environment variables remain supported for unattended deployments and migration,
but users should not need to edit them for normal desktop operation. Product builds
instead set `desktop/resources/product-profile.json`: `web` fixes one login-capable
source and `spreadsheet` fixes the built-in `imported` source. The backend rejects
source switching and plugin changes in those locked modes.

## Packaged internal edition

The Electron release bundles Python with PyInstaller. Supply the installed plugin
distribution name while building so both its modules and entry-point metadata are
included:

```powershell
$env:DEVICE_TUI_SOURCE_PLUGIN_DISTRIBUTIONS = "company-device-source"
$env:DEVICE_TUI_SOURCE_PLUGIN_MODULES = "company_device_source,internal_device"
Set-Location desktop
npm run dist
```

Multiple values may be comma-separated. Distribution names are used with
PyInstaller `--copy-metadata` so Entry Points remain discoverable; importable
module names are separately used with `--collect-all` so plugin code is bundled.
Both lists are validated before being passed to PyInstaller.

## Compatibility and failure behavior

- Source IDs must match `^[a-z][a-z0-9._-]{0,63}$`.
- Plugin API versions must match the core version.
- Duplicate source IDs are rejected.
- Built-in plugins cannot be disabled; external plugins can be disabled unless
  they are the active source.
- A plugin that fails to load or create its repository is marked unavailable;
  other sources and the App continue to work.
- Exactly one installed source may opt into the core Excel import workflow.
- Switching sources or replacing imported data remains blocked while terminal
  sessions exist.

Use `validate_device_repository()` in internal plugin tests to detect missing
protocol members before packaging.

The ready-to-run reference package lives at
`integration-templates/company-device-source`. It includes an in-memory website
API, complete repository mapping, login, inventory, occupancy actions, revision
waiting, and two demo devices. When the proprietary wrapper is ready, replace only
`company_device_source.binding.create_company_web_api()` with an object implementing
`CompanyWebApi`. Its README contains field mapping, Cookie ownership, direct reuse
of an existing repository factory, tests, and release commands.

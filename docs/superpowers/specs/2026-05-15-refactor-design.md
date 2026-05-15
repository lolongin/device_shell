# Device TUI 重构设计

## 背景

`desktop_app.py` 7169 行，为巨型单体文件，包含样式表、终端模拟、设备列表、命令记录、会话管理、主窗口等所有 UI 逻辑。此外缺少测试体系、导入路径脆弱、示例凭据与模型混在一起。

## 目标

1. 将 `desktop_app.py` 拆分为职责单一的模块
2. 理清设备对接层的契约边界，方便对接内部网站
3. 同步搭建 pytest 测试框架，为核心逻辑编写测试
4. 适度优化代码（清理重复导入、冗余 helper）

## 总体目录结构

```
src/
  __init__.py
  desktop_app.py          # 仅保留 import + main() 入口
  styles.py               # APP_STYLE + STATUS_COLORS

  # 设备对接层
  data.py                 # Device dataclass（不含示例数据）
  _sample_data.py         # sample_devices(), large_sample_devices()（从 data.py 剥离）
  repository.py           # DeviceRepository Protocol + SampleDeviceRepository + 异常
  api_client.py           # DeviceApiClient Protocol + HttpDeviceApiClient + 异常
  repo_factory.py         # create_repository_from_env（分离职责）

  # 公用组件
  helpers.py              # build_search_text, mask_password, status_color
  app_state.py            # RepositorySnapshot, DeviceTabState, SessionTabState
  async_utils.py          # AsyncLoopThread

  # UI 小组件
  widgets/
    __init__.py
    device_table.py       # CopyableDeviceTable, NoFocusItemDelegate
    terminal_widget.py    # InteractiveTerminal, TerminalSyntaxHighlighter
    command_record.py     # CommandRecordInput, CommandRecordResizeHandle
    search_input.py       # SelectAllLineEdit

  # 主窗口模块（Mixin 模式）
  app/
    __init__.py
    main_window.py        # DeviceDesktopApp（骨架 + 布局搭建）
    session_ops.py        # 会话管理 Mixin
    occupancy_ops.py      # 占用/电源管理 Mixin
    command_record_ops.py # 命令记录管理 Mixin
    desktop_state.py      # 桌面状态持久化 Mixin
    table_ops.py          # 设备/表格渲染 Mixin
```

## 设备层契约

GUI 只依赖以下接口，内部网站适配器只需实现对应 Protocol：

```
DeviceRepository (Protocol)     ← GUI 消费
  - fetch_devices()
  - toggle/claim/release/power_off_device()
  - current_user(), current_revision()
  - wait_for_update()

DeviceApiClient (Protocol)      ← HttpDeviceApiClient / 内部网站客户端
  - list_devices(), list_my_occupancy()
  - toggle/claim/release/power_off_device()
  - get_current_user(), current_revision(), wait_for_update()
```

- `SampleDeviceRepository` 保留在 `repository.py` 中作为内存实现
- 示例数据从 `data.py` 迁移到 `_sample_data.py`，不污染模型定义
- `repo_factory.py` 负责环境变量 -> 实现选择，从 `repository.py` 剥离

### Device 模型扩展

对于内站私有字段（硬件类型、板卡类型等），Device 模型增加 `extra` 字段：

```python
@dataclass(slots=True)
class Device:
    # ... 现有 24 个字段不变 ...
    extra: dict[str, Any] = field(default_factory=dict)
```

Adapter 映射时，标准字段填入 Device 属性，无法映射的私有字段放入 `extra`：

```python
class InternalSiteRepository:
    def fetch_devices(self) -> list[Device]:
        raw = self._api.get_devices()
        return [Device(
            id=raw.id, name=raw.name,
            # ... 标准字段映射 ...
            extra={
                "hardware_type": raw.hardware_type,
                "board_type": raw.board_type,
                # 任意内站私有字段
            }
        ) for raw in raw]
```

GUI 侧不依赖 `extra` 的具体键名，可在 detail 面板中提供通用键值对渲染区域。未来某字段被频繁使用时，可"提拔"为 Device 的正式字段。

## UI 模块拆分策略

`DeviceDesktopApp` 使用 Python 多继承 Mixin 拆分：

```python
class DeviceDesktopApp(                   # main_window.py
    SessionOpsMixin,                       # session_ops.py
    OccupancyOpsMixin,                     # occupancy_ops.py
    CommandRecordOpsMixin,                # command_record_ops.py
    DesktopStateMixin,                    # desktop_state.py
    TableOpsMixin,                        # table_ops.py
    QMainWindow,
):
```

每个 Mixin 类名以 `Mixin` 后缀标识（如 `SessionOpsMixin`），持有 `self` 引用访问共享状态。所有 Mixin 不定义 `__init__`，依赖 `DeviceDesktopApp.__init__` 初始化。

## 测试策略

- 使用 pytest，测试文件放在 `tests/`
- 优先为核心逻辑写测试：repository 层、app_state、helpers
- UI 组件只做 smoke test（能创建不报错）
- 暂不引入 GUI 自动化测试（QTest），未来可加

## 迁移计划

分 5 步增量进行，每步可独立提交和验证：

1. **准备阶段**：创建目录结构，提取 styles.py / helpers.py / app_state.py / async_utils.py
2. **设备层清理**：data.py 剥离示例数据，repo_factory.py 分离，清理 try/except 导入
3. **小组件提取**：device_table.py / terminal_widget.py / command_record.py / search_input.py
4. **主窗口拆分**：5 个 Mixin 文件 + 骨架 main_window.py
5. **测试搭建**：pytest 配置 + 核心逻辑测试

## 关键风险

- Mixin 间共享 `self` 状态，命名冲突需注意（加 `_mixin_` 前缀规避）
- `desktop_app.py` 不宜一口吃成胖子，每步后 `python src/desktop_app.py` 验证可运行

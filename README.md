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

# Go Device TUI

这个目录是按你当前 Python 版 `device_tui` 复刻的一份 Go 实现，功能目标保持一致：

- 左侧设备列表
- 左下我的占用
- 右侧设备详情
- 搜索 + Domain/Status/CPU 组合筛选
- `o` 占用/释放
- `p` 显隐密码
- `s` / `t` 直接发起 SSH / Telnet
- `S` / `T` 在新终端窗口里发起 SSH / Telnet

## 结构

- `main.go`: Bubble Tea TUI 布局、筛选、选中、连接动作
- `data.go`: `Device` 模型与示例数据生成
- `go.mod`: Go 模块定义

## 运行

需要 Go `1.22+`。

```bash
cd go-device-tui
go mod tidy
go run .
```

## 说明

为了贴近当前 Python 版，Go 版同样使用了内置样例数据，并保留了本地 SSH/Telnet 的演示入口。

界面库选的是 `Bubble Tea`，所以实现更偏消息驱动和状态机；视觉细节不会和 Textual 版完全像素级一致，但交互模型、信息结构和核心行为是一致的。

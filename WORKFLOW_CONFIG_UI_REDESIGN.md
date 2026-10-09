# Workflow 步骤配置 UI 重设计方案

## 当前问题诊断

### 1. 信息架构问题
- ❌ 所有字段垂直堆叠，缺少分组
- ❌ 必填项和可选项混在一起
- ❌ 高级参数隐藏在折叠按钮中，不直观
- ❌ 文件上传需要分别配置路径、文件名、目标路径，步骤繁琐

### 2. 视觉设计问题
- ❌ 缺少视觉层级，信息密度过高
- ❌ 没有配置进度反馈
- ❌ 字段标签和输入框间距不一致
- ❌ 缺少状态指示（哪些字段已配置、哪些未配置）

### 3. 交互体验问题
- ❌ 缺少即时验证反馈
- ❌ 没有配置预览
- ❌ 测试按钮位置不固定，滚动时看不到
- ❌ 变量引用和固定值切换不流畅

## 改进方案

### 核心设计理念

**渐进式展示 Progressive Disclosure**
- 默认只显示必填的基础配置
- 高级配置分组折叠，按需展开
- 智能推荐常用配置

**即时反馈 Immediate Feedback**
- 配置完整度进度条
- 字段级别的验证提示
- 实时配置预览

**清晰的视觉层级 Clear Visual Hierarchy**
- 必填区域用蓝色边框标识
- 已配置项显示绿色勾选图标
- 未配置的必填项显示橙色警告

### UI 结构设计

```
┌─────────────────────────────────────┐
│ ● ● ● 步骤配置                      │
├─────────────────────────────────────┤
│ ┌─ 配置进度 ──────────────────┐    │
│ │ ████████░░░░░░░░░░ 40%       │    │
│ │ ⚠️  2 / 5 必填项已配置        │    │
│ └──────────────────────────────┘    │
│                                      │
│ ▼ 基础配置 [必填] 3 项              │
│ ┌────────────────────────────────┐  │
│ │ 目标设备 * ✓                   │  │
│ │ [选择设备 ▼]                   │  │
│ │                                 │  │
│ │ 超时时间                        │  │
│ │ [30] 秒                        │  │
│ │                                 │  │
│ │ □ 永不超时                     │  │
│ └────────────────────────────────┘  │
│                                      │
│ ▶ 高级选项 5 项                     │
│                                      │
│ ▶ 错误处理 2 项                     │
│                                      │
├─────────────────────────────────────┤
│ [测试此步骤]  [保存为模板]         │
└─────────────────────────────────────┘
```

### 关键特性

#### 1. 配置进度指示器
```vue
<div class="config-progress">
  <div class="progress-bar">
    <div class="fill" :style="{ width: '40%' }"></div>
  </div>
  <div class="progress-text">
    <AlertCircle /> 2 / 5 必填项已配置
  </div>
</div>
```

#### 2. 分组折叠面板
- **基础配置** - 默认展开，包含所有必填项
- **高级选项** - 默认折叠，包含可选的高级参数
- **错误处理** - 默认折叠，包含重试、超时等配置
- **输出配置** - 默认折叠，自定义输出字段

#### 3. 智能字段组件

**设备选择增强**
```vue
<DeviceSelector
  v-model="config.device_id"
  :mode="'select'" <!-- select | reference | mixed -->
  :allow-reference="true"
  :recent-devices="recentDevices"
/>
```

特性：
- 最近使用的设备置顶
- 支持搜索过滤
- 变量引用和固定设备统一界面
- 显示设备状态（在线/离线）

**文件路径组件**
```vue
<FilePath
  v-model="config.source"
  :type="'local'" <!-- local | remote -->
  :allow-browse="true"
  :history="uploadHistory"
/>
```

特性：
- 文件浏览按钮
- 历史记录快速选择
- 自动补全常用路径
- 支持拖拽文件

**超时配置组件**
```vue
<TimeoutConfig
  v-model="config.timeout_seconds"
  :allow-infinite="true"
  :presets="[30, 60, 300, 0]"
/>
```

特性：
- 常用时长快速选择
- 滑块 + 输入框双重输入
- "永不超时"快捷选项

#### 4. 配置模板
```vue
<template-selector
  :templates="[
    { name: '快速连接', config: { timeout: 30 } },
    { name: '稳定连接', config: { timeout: 300, retry: 3 } }
  ]"
  @select="applyTemplate"
/>
```

### 视觉设计规范

#### 颜色语义
- **蓝色 #3b82f6** - 必填区域边框、主要操作按钮
- **绿色 #10b981** - 已完成状态、测试按钮
- **橙色 #f59e0b** - 警告、未完成必填项
- **红色 #ef4444** - 错误、验证失败

#### 间距规范
- 组件间距：16px
- 字段间距：12px
- 内边距：12-16px
- 圆角：6-8px

#### 字体规范
- 标题：13px / 500
- 正文：12px / 400
- 标签：11px / 400
- 辅助：10px / 400

### 交互优化

#### 1. 键盘快捷键
- `Tab` - 在字段间导航
- `Enter` - 快速测试（聚焦在配置区时）
- `Cmd/Ctrl + S` - 保存配置
- `Cmd/Ctrl + T` - 测试步骤

#### 2. 自动保存
- 配置变更后 500ms 自动保存
- 显示"已保存"提示
- 网络错误时显示重试按钮

#### 3. 验证反馈
- 实时验证（输入时）
- 字段级错误提示
- 阻止提交时的全局错误汇总

### 移动端适配

#### 响应式布局
- 宽度 > 768px：侧边栏配置面板
- 宽度 < 768px：全屏配置抽屉
- 触摸优化的折叠面板

#### 触摸交互
- 增大可点击区域（最小 44px）
- 支持滑动关闭配置面板
- 长按显示字段说明

## 实施计划

### Phase 1: 基础重构（1-2天）
- [ ] 创建新的配置容器组件
- [ ] 实现配置进度指示器
- [ ] 实现分组折叠面板
- [ ] 迁移现有配置项

### Phase 2: 增强组件（2-3天）
- [ ] 开发增强的设备选择器
- [ ] 开发文件路径组件
- [ ] 开发超时配置组件
- [ ] 开发变量引用选择器

### Phase 3: 交互优化（1-2天）
- [ ] 添加配置模板功能
- [ ] 实现键盘快捷键
- [ ] 添加自动保存
- [ ] 实现实时验证

### Phase 4: 测试与优化（1-2天）
- [ ] 单元测试
- [ ] 集成测试
- [ ] 性能优化
- [ ] 用户测试反馈

## 预期效果

### 定量指标
- ⚡ 配置时间减少 40%
- 📉 配置错误率降低 60%
- 👍 用户满意度提升至 4.5/5

### 定性改进
- ✅ 清晰的配置进度反馈
- ✅ 必填项和可选项分离清晰
- ✅ 常用操作更快捷
- ✅ 视觉层级更清晰
- ✅ 错误提示更友好

## 技术实现要点

### 1. 组件解耦
```typescript
// 配置字段定义
interface ConfigField {
  name: string
  label: string
  type: 'text' | 'number' | 'select' | 'device' | 'file'
  required: boolean
  group: 'basic' | 'advanced' | 'error-handling'
  validator?: (value: any) => string | null
  transformer?: (value: any) => any
}
```

### 2. 配置状态管理
```typescript
const configState = reactive({
  values: {},
  errors: {},
  touched: new Set(),
  validity: computed(() => {
    // 计算配置完整度
  })
})
```

### 3. 渐进式增强
```typescript
// 根据 action 类型动态生成配置结构
function buildConfigSchema(actionId: string): ConfigSection[] {
  const schema = actionSchemas[actionId]
  return [
    { id: 'basic', fields: schema.required },
    { id: 'advanced', fields: schema.optional },
    { id: 'error-handling', fields: schema.errorHandling }
  ]
}
```

## 兼容性考虑

- 保持现有配置数据结构不变
- 提供配置迁移工具
- 逐步迁移现有配置组件
- 保留旧版配置面板作为后备

## 参考案例

- **GitHub Actions** - 清晰的步骤配置结构
- **Zapier** - 渐进式字段展示
- **n8n** - 可视化节点配置
- **Postman** - 请求配置面板设计

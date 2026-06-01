# Textual TUI 面板式界面设计

## 概述

用 Textual 框架替换现有的 print-based CLI（`duck run` 命令），实现面板式 TUI：左侧消息历史（完整 GFM markdown 渲染），右侧 agent 详细状态，底部自适应输入框。

typer 的 `log` 和 `send` 子命令保持不变，只替换 `run` 的交互模式。

## 架构决策

**方案：Textual 全接管**

Textual App 作为主事件循环。agent 生命周期由 App 生命周期驱动（on_mount 启动，on_unmount 停止）。MessageBus 的 asyncio.Queue 直接在 Textual 的 asyncio loop 中消费，无需桥接层。

理由：Textual 本身跑在 asyncio 上，和现有的 MessageBus + agent 架构天然兼容，同一个事件循环，不存在竞态问题。

## 布局

```
┌─────────────────────────────────┬──────────────┐
│  Messages (70%)                 │ Agents (30%) │
│                                 │              │
│  [10:32] you → main_agent      │ ┌──────────┐ │
│  分析 trace 里的加密算法          │ │main_agent│ │
│                                 │ │● thinking│ │
│  [10:33] main_agent → you       │ │处理: ... │ │
│  ## AES-128-CBC                 │ │结论: ... │ │
│  - Key schedule at `0x1A40`     │ └──────────┘ │
│  - S-Box: `0x2000-0x20FF`      │ ┌──────────┐ │
│                                 │ │trace_agent││
│                                 │ │● idle    │ │
│                                 │ │等待任务   │ │
│                                 │ │结论: ... │ │
│                                 │ └──────────┘ │
├─────────────────────────────────┴──────────────┤
│ > ▊ (自适应输入框)                               │
│   Enter 发送 | Shift+Enter 换行                  │
└────────────────────────────────────────────────┘
```

## 组件树

```
DuckApp(App)
├── Horizontal
│   ├── VerticalScroll#messages        # 消息历史，70% 宽度
│   │   └── MessageWidget*             # 每条消息一个 widget
│   │       ├── MessageHeader          # from → to, timestamp
│   │       └── Markdown               # Textual 原生 Markdown widget
│   └── VerticalScroll#agents          # agent 面板，30% 宽度
│       └── AgentCard*                 # 每个 agent 一张卡片
│           ├── agent_name + StatusIndicator
│           ├── current_task label
│           └── last_conclusion label
├── InputArea#input                    # 自适应高度的 TextArea
└── Footer                             # 快捷键提示栏
```

## 核心组件设计

### DuckApp

- 继承 `textual.app.App`
- `on_mount()`: 初始化 MessageBus → 启动 MainAgent + TraceAgent → 订阅 human queue → 启动消息消费 worker
- `on_unmount()`: 停止 agents → 关闭 bus
- CSS 文件控制布局比例和主题

### MessageWidget

- 自定义 `Static` 组合 widget
- MessageHeader: 显示 `from_agent → to_agent` + 时间戳，带颜色区分
- 内容部分使用 Textual 的 `Markdown` widget，支持完整 GFM（标题、代码块高亮、表格、列表、引用）
- 新消息 mount 后自动 scroll_end

### AgentCard

- 自定义 widget，显示单个 agent 的实时状态
- 状态指示：idle（灰）/ thinking（黄）/ tool_calling（蓝）
- 当前任务：正在处理的消息摘要（截断到一行）
- 最近结论：最后一条 conclusion 消息的摘要

### InputArea

- 基于 Textual 的 `TextArea` widget
- 默认高度 1 行，内容超出时自动扩展（最大 10 行）
- Enter 发送消息，Shift+Enter 插入换行
- 发送后清空并恢复单行高度

## 数据流

```
用户输入 → InputArea → Message(from=human, to=main_agent) → MessageBus
                                                                ↓
MessageBus → human_queue → DuckApp worker → mount MessageWidget
MessageBus → agent status → DuckApp worker → update AgentCard
```

### Agent 状态更新机制

在 BaseAgent 中新增状态广播：agent 在 `think()` 开始时广播 `status: thinking`，tool call 时广播 `status: tool_calling`，完成时广播 `status: idle`。

消息类型扩展：在现有 Message.type 中新增 `"status"` 类型，content 为 JSON 编码的状态信息：

```python
{
    "state": "thinking" | "tool_calling" | "idle",
    "task_summary": "分析加密算法请求",  # 可选
    "last_conclusion": "AES-128-CBC 识别完成"  # 可选
}
```

status 消息不经过自校验（不是 conclusion），不持久化到 SQLite（纯内存分发）。

## 文件结构

```
src/duckagent/cli/
├── app.py              # typer 入口（保留 log/send，run 改为启动 TUI）
├── tui/
│   ├── __init__.py
│   ├── app.py          # DuckApp 主类
│   ├── app.tcss        # Textual CSS 布局
│   ├── widgets/
│   │   ├── __init__.py
│   │   ├── message.py  # MessageWidget + MessageHeader
│   │   ├── agent_card.py  # AgentCard
│   │   └── input_area.py  # InputArea (自适应 TextArea)
│   └── worker.py       # bus 消息消费 → UI 更新的 worker
```

## 依赖变更

新增：
- `textual>=3.0` — TUI 框架

保留：
- `typer>=0.12.0` — 非 TUI 子命令（log, send）

## 对现有代码的改动

1. **`cli/app.py`**: `run` 命令改为调用 `DuckApp().run()`，删除 `_run_interactive` 及相关函数
2. **`agents/base.py`**: `think()` 方法中加入状态广播（3 行左右）
3. **`bus/store.py`**: MessageBus 支持 ephemeral 消息（status 类型不写 SQLite）
4. **`bus/models.py`**: Message.type 增加 `"status"` 选项
5. **`pyproject.toml`**: 添加 `textual` 依赖

## 快捷键

| 快捷键 | 动作 |
|--------|------|
| Enter | 发送消息 |
| Shift+Enter | 输入换行 |
| Ctrl+C | 退出 |
| Ctrl+L | 清屏消息历史 |

## 不做的事

- 不做 headless 模式回退（直接替换，不维护两套）
- 不做 agent 手动启停控制
- 不做消息编辑/删除
- 不做主题切换（先用 Textual 默认暗色主题）

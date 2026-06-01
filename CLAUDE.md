# Android 逆向 Multi-Agent 系统

## 项目概述

多 Agent 协作系统，用于 Android 逆向工程。群聊模型，agent 之间通过消息总线交换结论性信息。

当前阶段：Phase 1 — 主 Agent + Trace Agent + 消息总线 + Textual TUI。

## 技术栈

- 语言：Python 3.12+
- 模型调用：litellm（统一接口，切模型只改配置）
- 消息总线：SQLite 持久化 + asyncio.Queue 内存分发
- Trace 工具：ak_search（C daemon，mmap + 行索引）
- 包管理：uv
- CLI：typer + Textual TUI

## 架构

```
┌─────────────────────────────────────────────────────────┐
│  单进程 (asyncio)                                       │
│                                                        │
│  Textual TUI ←→ 主Agent ←→ 消息总线 ←→ TraceAgent      │
│                         (SQLite)    (tool calling)      │
│                                     ↓                  │
│                               ak_search daemon         │
│                               (code/rw/bl.log)         │
└─────────────────────────────────────────────────────────┘
```

### 角色

| 角色 | 职责 | 工具 |
|------|------|------|
| 主Agent | 接收用户输入、拆解任务、分发、综合结论 | 无（纯推理） |
| TraceAgent | 执行流分析、算法还原 | trace_search/trace_context/trace_cross_ref |
| 人（Leader） | 终审、路径决策 | Textual TUI |

### 未来角色

| 角色 | 职责 | 工具 |
|------|------|------|
| IDA+Jadx | 静态分析、函数识别 | IDA MCP、Jadx MCP |
| Unidbg | 补环境、模拟执行、验证 | unidbg Java API |

## TUI

基于 Textual 框架，面板式布局。`duck run` 启动 TUI 模式，`duck log`/`duck send` 保留为纯命令行模式。

```
┌─────────────────────────────────┬──────────────┐
│  Messages                       │ Agents       │
│                                 ├──────────────│
│  [14:25] you → main_agent      │ main_agent   │
│  你好                          │ ● idle       │
│                                 │ 处理: -      │
│  [14:25] main_agent → you       │ 结论: -      │
│  你好！有什么逆向分析...          ├──────────────│
│                                 │ trace_agent  │
│                                 │ ● idle       │
│                                 │ 处理: -      │
│                                 │ 结论: -      │
├─────────────────────────────────┴──────────────┤
│ > 输入消息... (Enter 发送, Ctrl+D 退出)         │
└────────────────────────────────────────────────┘
```

- 左侧消息区：GFM markdown 渲染（代码高亮、表格、列表）
- 右侧 Agent 状态面板：实时显示 idle/thinking/tool_calling
- 自适应输入框，Enter 发送
- Ctrl+D 退出，Ctrl+L 清屏

## 通信机制

群聊模型。每个 agent 有独立上下文，不共享对话历史，只通过消息总线交换结论。

消息结构：
```python
class Message(BaseModel):
    id: str                          # uuid4
    from_agent: str                  # "human", "main_agent", "trace_agent"
    to_agent: str | None             # None = 广播, specific = 私信
    type: Literal["conclusion", "request", "question", "decision", "status"]
    content: str
    evidence: list[str]
    confidence: Literal["high", "medium", "low"]
    timestamp: datetime
    reply_to: str | None
```

规则：
- `to_agent: "specific_agent"` = 私信，`to_agent: None` = 广播
- `to_agent: "human"` = 上报给人
- 消息不可变，发出去不能改
- agent 只交换结论，不汇报进度
- status 类型消息纯内存分发，不写 SQLite

### 主 Agent 路由

主 Agent 不要求模型输出 JSON。用自然语言 + 文本标记路由：

- 模型输出自然语言 markdown 回复
- 需委托 trace_agent 时，首行写 `>>> DELEGATE TO trace_agent`，下面写具体任务
- 对话性消息（≤3字且无分析关键词）直接短路回复，不调 LLM

### Agent 状态广播

Agent 在 `think()` 中自动广播状态（thinking / tool_calling / idle），用于 TUI 状态面板更新。状态消息 type="status"，不持久化，不触发校验。

### 自校验

**当前已全局关闭**。历史证明每句都要自查 + 自查又调 think() = 死循环。等有明确场景再重新设计：
- 只对关键结论（安全判断、算法确定）触发
- 校验失败不重试，降级 confidence 交用户裁决
- 校验和重试分离

## 目录结构

```
src/duckagent/
├── __init__.py
├── bus/
│   ├── models.py          # Message 数据模型
│   └── store.py           # MessageBus: SQLite + Queue 分发
├── agents/
│   ├── base.py            # BaseAgent: 生命周期、think()、send()、状态广播
│   ├── main_agent.py      # MainAgent: 路由、casual 短路、DELEGATE 标记
│   └── trace_agent.py     # TraceAgent: tool calling 分析 trace
├── tools/
│   ├── protocol.py        # ToolExecutor protocol
│   ├── schemas.py         # trace tool schemas
│   └── trace_executor.py  # LocalTraceToolExecutor (ak_search daemon)
├── verify/
│   ├── hard.py            # 硬校验
│   └── self_check.py      # 模型自查
├── cli/
│   ├── app.py             # typer CLI: run/log/send
│   └── tui/
│       ├── app.py         # DuckApp (Textual)
│       ├── app.tcss       # CSS 布局 + GitHub-dark 配色
│       ├── worker.py      # bus 消息 → UI 更新
│       └── widgets/
│           ├── input_area.py   # 自适应输入框
│           ├── message.py      # Markdown 消息渲染
│           └── agent_card.py   # Agent 状态卡片
└── config.py              # pydantic-settings 配置
tools/search/              # ak_search C 源码 + 编译产物
prompts/                   # agent system prompts
```

## 使用方式

```bash
# 启动 TUI 交互模式
uv run duck run

# 查看消息历史
uv run duck log
uv run duck log --from trace_agent --limit 10

# 发送单条消息（非交互）
uv run duck send "分析 trace 里的加密算法"

# 运行测试
uv run pytest tests/ -v
```

## 配置

通过 `.env` 文件（不提交到 git）：

```bash
# DeepSeek 官方 API（OpenAI 兼容）
OPENAI_API_KEY=sk-xxx
OPENAI_API_BASE=https://api.deepseek.com/v1
DUCKAGENT_LITELLM_MODEL=openai/deepseek-chat

# Trace 文件
DUCKAGENT_TRACE_CODE_FILE=/path/to/code.log
DUCKAGENT_TRACE_RW_FILE=/path/to/rw.log
DUCKAGENT_TRACE_BL_FILE=/path/to/bl.log

# 自校验（已关闭）
DUCKAGENT_VERIFY_ENABLED=false
DUCKAGENT_VERIFY_MAX_RETRIES=3
```

## Trace 文件格式

三文件结构：
- **code.log** — 汇编 trace：`行号 : 绝对地址 [相对偏移] "指令" (r/w)寄存器=值`
- **rw.log** — 内存读写：`行号: (r/w)(基址+偏移)` + hexdump
- **bl.log** — PLT/函数调用：`code行号: [跳转地址][参数索引]: 函数符号名` + 参数 dump

TraceAgent 通过 tool calling 自主搜索这些文件，不需要手动切片。

## 编码规范

- 类型注解：所有函数签名必须有 type hints
- 数据模型：Pydantic v2
- 异步：agent 循环用 asyncio，TUI 用 Textual 的 asyncio 事件循环
- 错误处理：不吞异常，该 raise 就 raise
- 日志：structlog
- 配置：环境变量 + .env，不硬编码 key

## 设计原则

- agent 之间零耦合，只通过消息总线通信
- 消息总线是低频高密度的，不是工作日志
- 宁可上报人也不要让错误结论通过
- 不要过度设计，先跑通再迭代
- Agent 的 prompt 是核心

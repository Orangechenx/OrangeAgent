# Android 逆向 Multi-Agent 系统

## 项目概述

多 Agent 协作系统，用于 Android 逆向工程。Agent 平权——通过 @mention 互相点名，不设中心路由。

当前阶段：Phase 3 — HTTP 消息总线 + 多进程 + Textual TUI。

## 技术栈

- 语言：Python 3.12+
- 模型调用：litellm（统一接口，切模型只改配置）
- 消息总线：MessageBus ABC → LocalMessageBus（SQLite + asyncio.Queue）+ HttpMessageBus（HTTP + WebSocket）
- 服务端：FastAPI + uvicorn（独立进程）
- Trace 工具：ak_search（C daemon，mmap + 行索引）
- JADX 工具：HTTP 直连 JADX Java Plugin（127.0.0.1:8650）
- 包管理：uv
- CLI：typer + Textual TUI
- 下一阶段：Unidbg Agent、重连机制、HTTP 双向 WebSocket 优化

## 架构

### 多进程模式（`duck launch`）

```
进程: bus-server (FastAPI + SQLite + WebSocket)     :8720
进程: main-agent  ──┐
进程: trace-agent ──┼── HTTP POST /api/v1/publish + WS /ws?agent_id=<id>
进程: ida-agent   ──┘
进程: tui         ──── WS /ws?role=observer (看全部) + HTTP POST (发消息)
```

### 单进程模式（`duck run`，向后兼容）

```
┌──────────────────────────────────────────────────────────────────┐
│  单进程 (asyncio)                                                │
│                                                                  │
│                     ┌─────────────┐                              │
│  Textual TUI ←───→  │   人类      │                              │
│                     └─────────────┘                              │
│                           │                                      │
│         @trace_agent      │      @ida_jadx_agent                 │
│              ┌────────────┼────────────┐                         │
│              ▼            │            ▼                         │
│  ┌──────────────┐  ┌──────────┐  ┌───────────────┐              │
│  │ TraceAgent   │  │MainAgent │  │ IdaJadxAgent  │              │
│  │ (ak_search)  │  │ (纯推理) │  │ (JADX HTTP)   │              │
│  └──────┬───────┘  └────┬─────┘  └───────┬───────┘              │
│         │               │                │                       │
│         └───────────────┼────────────────┘                       │
│                         ▼                                        │
│              ┌─────────────────────┐                             │
│              │ MessageBus (SQLite) │                             │
│              └─────────────────────┘                             │
└──────────────────────────────────────────────────────────────────┘
```

### 角色

| 角色 | agent_id | 职责 | 工具 |
|------|----------|------|------|
| MainAgent | main_agent | 协调、拆解任务、综合结论 | 无（纯推理） |
| TraceAgent | trace_agent | 执行流分析、算法还原 | trace_search/trace_context/trace_cross_ref |
| IdaJadxAgent | ida_jadx_agent | 静态代码分析、类/方法搜索 | jadx_search_classes_by_keyword/get_class_source/xrefs 等 11 个 |
| 人（Leader） | human | 终审、路径决策 | Textual TUI |

### 未来角色

| 角色 | 职责 | 工具 |
|------|------|------|
| Unidbg | 补环境、模拟执行、验证 | unidbg Java API |

## TUI

基于 Textual 框架，面板式布局。`duck run` 启动 TUI 模式，`duck log`/`duck send` 保留为纯命令行模式。

```
┌─────────────────────────────────────────┬──────────────┐
│  Messages                               │ Agents       │
│                                         ├──────────────│
│  📤 [14:25] you → main_agent @trace ▎🔵│ main_agent   │
│  分析这个 trace 里的签名算法         ▎  │ ● idle       │
│                                         │ 处理: -      │
│  📤 [14:25] main_agent → all       ▎⚪│ 结论: -      │
│  [@trace_agent]                     ▎  ├──────────────│
│  @trace_agent 分析 AES 加密...      ▎  │ trace_agent  │
│                                         │ ● thinking   │
│  📋 [14:26] trace_agent → main     ▎⚪│ 处理: ...    │
│  发现 HMAC-SHA256 签名...          ▎  │ 结论: -      │
│                                         ├──────────────│
│  📋 [14:27] main_agent → you       ▎🟢│ ida_jadx_ag  │
│  分析结果：签名算法是 HMAC-SHA256  ▎  │ ● idle       │
├─────────────────────────────────────────┴──────────────┤
│ > 输入消息... (Enter 发送, Ctrl+D 退出)                 │
└────────────────────────────────────────────────────────┘
```

- 左侧消息区：GFM markdown 渲染（代码高亮、表格、列表），TUI 通过 Observer 模式看到所有消息
- 消息左边框颜色区分：🔵 你的消息 / 🟢 回复给你的 / ⚪ agent 内部通信
- messages header 显示 @mentions：`[@trace_agent, @ida_jadx_agent]`
- 右侧 Agent 状态面板：实时显示 idle/thinking/tool_calling
- 自适应输入框，Enter 发送，支持 @agent_id 语法
- 启动时异步加载最近 20 条历史消息，不阻塞 UI
- Ctrl+D 退出，Ctrl+L 清屏

## 通信机制

### @mention 路由（Agent 平权）

任何 agent 可以通过 `@agent_id` 直接点名其他 agent，不再通过 MainAgent 中心路由。

```
Human: "@trace_agent 分析签名"          → trace_agent 处理
trace_agent: "发现 HMAC, @ida_jadx_agent 确认"  → ida_jadx_agent 处理
ida_jadx_agent: "确认 Mac 类, @trace_agent"      → trace_agent 继续
trace_agent: "@human 算法是 HMAC-SHA256"          → human 收到
```

路由规则：
- `to_agent` + `mentions` 双重路由，取并集
- `mentions` 从 content 中的 `@agent_id` 自动解析
- 发件人永远不收自己的消息
- 无显式收件人时广播（backward compat）

### 消息结构

```python
class Message(BaseModel):
    id: str                          # uuid4
    from_agent: str                  # "human", "main_agent", "trace_agent", "ida_jadx_agent"
    to_agent: str | None             # None = 广播, specific = 私信
    mentions: list[str]              # @agent_id 列表，多收件人
    type: Literal["conclusion", "request", "question", "decision", "status"]
    content: str
    evidence: list[str]
    confidence: Literal["high", "medium", "low"]
    timestamp: datetime
    reply_to: str | None
```

### 消息类型语义

| type | 含义 | 是否触发 agent 动作 |
|------|------|-------------------|
| request | 请求执行任务 | ✅ 是 |
| question | 需要回答的问题 | ✅ 是 |
| conclusion | 结论/报告/信息 | ❌ 否（CC 而已） |
| decision | 决策/判定 | ❌ 否 |
| status | Agent 状态广播 | ❌ 否，纯内存不持久化 |

Agent 的 `on_message()` 只响应 `request` 和 `question` 类型。被 @mention 在 conclusion 里只是 CC，不触发动作。

### 上下文管理

**关键设计：bus 消息 ≠ LLM 上下文。**

每条消息是独立请求。`think()` 每次调用从 system prompt + 当前输入构建上下文，工具调用循环在同一个 `think()` 内局部扩展，函数返回后丢弃。不跨消息累积。

### Agent 状态广播

Agent 在 `think()` 中自动广播状态（thinking / tool_calling / idle），用于 TUI 状态面板更新。状态消息 type="status"，不持久化，不触发校验。

### 自校验

**当前已全局关闭**。历史证明每句都要自查 + 自查又调 think() = 死循环。等有明确场景再重新设计：
- 只对关键结论（安全判断、算法确定）触发
- 校验失败不重试，降级 confidence 交用户裁决
- 校验和重试分离

## 消息总线：双模式

### LocalMessageBus（单进程）

- SQLite 持久化 + asyncio.Queue 内存分发
- `_dispatch()` 在发布端解析收件人，直接 put 到队列
- 测试和开发默认使用

### HttpMessageBus（多进程）

- HTTP POST `/api/v1/publish` 发布消息
- WebSocket `/ws?agent_id=<id>` 接收消息（服务端推送）
- 路由逻辑在 FastAPI 服务端（`server/dispatcher.py`）
- `ConnectionManager` 管理三种连接：agent、observer、status
- `subscribe()` 保持同步返回 `asyncio.Queue`——Agent 代码零改动

### Bus Server API

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/v1/publish` | POST | 发布消息，非 status 持久化 |
| `/api/v1/history` | GET | 查询历史（支持 from/type/limit 过滤） |
| `/api/v1/health` | GET | 健康检查 |
| `/ws?agent_id=<id>` | WS | Agent 连接，服务端过滤推送 |
| `/ws?role=observer` | WS | Observer 连接，推送全部消息 |
| `/ws?role=status` | WS | Status 连接，仅推送状态消息 |

## 目录结构

```
src/duckagent/
├── __init__.py
├── bus/
│   ├── interface.py       # MessageBus ABC（8 个抽象方法）
│   ├── models.py          # Message 数据模型（含 mentions）
│   ├── store.py           # LocalMessageBus: SQLite + Queue 分发
│   └── http_client.py     # HttpMessageBus: HTTP POST + WebSocket 接收
├── server/
│   ├── app.py             # FastAPI app + lifespan
│   ├── routes.py          # REST + WebSocket 端点
│   ├── ws_manager.py      # ConnectionManager（agent/observer/status）
│   ├── db.py              # SQLite 持久层
│   └── dispatcher.py      # 纯函数路由逻辑
├── agents/
│   ├── base.py            # BaseAgent: 生命周期、think()、send()、@mention 解析
│   ├── main_agent.py      # MainAgent: @mention 路由、JSON 清理
│   ├── trace_agent.py     # TraceAgent: tool calling 分析 trace
│   └── ida_jadx_agent.py  # IdaJadxAgent: JADX 静态分析
├── processes/
│   ├── agent_process.py   # Agent 进程入口（工厂 + 信号处理）
│   └── tui_process.py     # TUI 进程入口（HttpMessageBus observer 模式）
├── tools/
│   ├── protocol.py        # ToolExecutor protocol
│   ├── schemas.py         # trace + JADX tool schemas
│   ├── trace_executor.py  # LocalTraceToolExecutor (ak_search daemon)
│   └── jadx_executor.py   # JadxToolExecutor (HTTP → JADX Java Plugin)
├── verify/
│   ├── hard.py            # 硬校验
│   └── self_check.py      # 模型自查
├── cli/
│   ├── app.py             # typer CLI: run/log/send/server/launch/agent
│   └── tui/
│       ├── app.py         # DuckApp (Textual): local/http 双模式
│       ├── app.tcss       # CSS 布局 + GitHub-dark 配色
│       ├── worker.py      # Observer → UI
│       └── widgets/
│           ├── input_area.py   # 自适应输入框
│           ├── message.py      # Markdown 消息渲染
│           └── agent_card.py   # Agent 状态卡片
├── launcher.py            # 多进程启动器（subprocess.Popen）
└── config.py              # pydantic-settings 配置
tools/search/              # ak_search C 源码 + 编译产物
prompts/                   # agent system prompts
```

## 使用方式

```bash
# === 单进程模式（开发/测试） ===

# 启动 TUI（agent 运行在同一进程）
uv run duck run

# 纯命令行
uv run duck send "@trace_agent 分析签名"
uv run duck log --from trace_agent --limit 10

# === 多进程模式（生产） ===

# 一键启动全部进程（server + 3 agents + TUI）
uv run duck launch --port 8720

# 或手动分步启动：
uv run duck server --port 8720              # 终端 1: 总线服务
uv run duck agent main_agent --server-url http://127.0.0.1:8720   # 终端 2
uv run duck agent trace_agent --server-url http://127.0.0.1:8720  # 终端 3
uv run duck agent ida_jadx_agent --server-url http://127.0.0.1:8720  # 终端 4
uv run duck run --transport http --server-url http://127.0.0.1:8720  # 终端 5: TUI

# 直接用 curl 调试
curl http://127.0.0.1:8720/api/v1/history
curl -X POST http://127.0.0.1:8720/api/v1/publish \
  -H "Content-Type: application/json" \
  -d '{"from_agent":"human","to_agent":"main_agent","mentions":[],"type":"request","content":"hello","evidence":[],"confidence":"high"}'

# 运行测试
uv run pytest tests/ -v
```

## 配置

通过 `.env` 文件（不提交到 git）：

```bash
# === LLM ===
OPENAI_API_KEY=sk-xxx
OPENAI_API_BASE=https://api.deepseek.com/v1
DUCKAGENT_LITELLM_MODEL=openai/deepseek-chat

# === 消息总线 ===
DUCKAGENT_BUS_TRANSPORT=local           # local | http
DUCKAGENT_BUS_SERVER_HOST=127.0.0.1
DUCKAGENT_BUS_SERVER_PORT=8720

# === 数据库 ===
DUCKAGENT_DB_DIR=.duckagent

# === Trace 文件 ===
DUCKAGENT_TRACE_CODE_FILE=/path/to/code.log
DUCKAGENT_TRACE_RW_FILE=/path/to/rw.log
DUCKAGENT_TRACE_BL_FILE=/path/to/bl.log

# === JADX ===
DUCKAGENT_JADX_HOST=127.0.0.1
DUCKAGENT_JADX_PORT=8650

# === 自校验（已关闭） ===
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
- **bus 消息 ≠ LLM 上下文**，每条消息独立，不跨消息累积
- **Agent 只响应 request/question，被 @ 在 conclusion 里只是 CC**
- 宁可上报人也不要让错误结论通过
- 不要过度设计，先跑通再迭代
- Agent 的 prompt 是核心
- MessageBus ABC 使得切换 local ↔ http 只需换实现，Agent 代码不动

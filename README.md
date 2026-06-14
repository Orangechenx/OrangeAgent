# OrangeAgent — Android 逆向 Multi-Agent 系统

多 Agent 协作系统，用于 Android 逆向工程。Agent 平权——通过 `@agent_id` 互相点名，不设中心路由。

## 快速开始

```bash
# 1. 安装依赖
uv sync

# 2. 配置 LLM（.env）
cp .env.example .env
# 编辑 .env 填入 API key 和模型

# 3. 启动（单进程，开箱即用）
uv run orange run

# 4. 多进程模式
uv run orange launch --port 8720
```

## 架构

```
┌─────────────────────────────────────────────────────────────┐
│  多进程模式                                                  │
│                                                             │
│  bus-server (FastAPI :8720)  ←── HTTP + WebSocket           │
│       ↑                                                     │
│       ├── main-agent 进程    (协调、路由)                    │
│       ├── network-agent 进程 (网络流量分析)                  │
│       ├── ida-jadx-agent 进程 (JADX 静态分析)               │
│       ├── trace-agent 进程   (ARM64 执行流分析)              │
│       ├── frida-agent 进程   (动态 Hook)                    │
│       ├── apktool-agent 进程 (APK 解包/重打包)              │
│       ├── js-reverse-agent 进程 (JS 逆向)                   │
│       ├── ida-agent 进程     (IDA Native 分析)              │
│       ├── unidbg-agent 进程  (SO 模拟执行)                  │
│       └── tui 进程 (Textual 终端界面)                       │
│                                                             │
│  也支持单进程模式 (orange run) —— 所有 agent 在同一 asyncio    │
│  进程内通过 asyncio.Queue 通信，适合开发调试。               │
└─────────────────────────────────────────────────────────────┘
```

| Agent | 职责 | 工具 | 覆盖层 |
|-------|------|------|--------|
| **MainAgent** | 协调、拆解任务、路由 | 无（纯推理） | 管理层 |
| **NetworkAgent** | 网络流量分析、签名定位 | httpx (2) | L1 黑盒观测 |
| **IdaJadxAgent** | APK 静态代码反编译 | JADX HTTP API (11) | L2 Java 静态 |
| **FridaAgent** | 运行时 Hook、类枚举 | frida Python (6) | L3 Java Hook |
| **ApktoolAgent** | APK 解包、Smali 修改、重打包 | apktool CLI (4) | L4 Smali 字节码 |
| **JsReverseAgent** | WebView JS 反混淆、格式化 | node/js-beautify (3) | L2 WebView |
| **IdaAgent** | Native 二进制深度分析 | ida-pro-mcp (5) | L6 Native 静态 |
| **TraceAgent** | ARM64 指令级 trace 分析 | ak_search (3) | L10 指令级 trace |
| **UnidbgAgent** | Native SO 模拟执行、算法复现 | unidbg-0.9.9 (2) | L10-L11 模拟/算法 |
| **JsReverseAgent** | WebView JS 反混淆、格式化 | node/js-beautify (3) | L2 WebView |
| **IdaAgent** | Native 二进制深度分析 | ida-pro-mcp (5) | L6 Native 静态 |
| **TraceAgent** | ARM64 指令级 trace 分析 | ak_search (3) | L10 指令级 trace |
| **UnidbgAgent** | Native SO 模拟执行、算法复现 | unidbg-0.9.9 (2) | L10-L11 模拟/算法 |

> 全部 46 个工具均通过 ToolRegistry 自注册，可用 `orange tools` 查看审计记录。

### 通信机制

Agent 通过 `@agent_id` 互相点名，平权路由：

```
Human: "@trace_agent 分析签名"          → trace_agent
trace_agent: "发现 HMAC, @ida_jadx_agent" → ida_jadx_agent
ida_jadx_agent: "@trace_agent 确认了"     → trace_agent
trace_agent: "结论: HMAC-SHA256"          → human
```

- `request` / `question` 触发 Agent 动作
- `conclusion` / `decision` 仅通知，不触发
- `status` 不持久化，仅 UI 状态更新

## 使用

```bash
# ── TUI 交互 ──
uv run orange run                         # 单进程 TUI
uv run orange run --transport http        # 多进程 TUI（需先启动 server）

# ── 多进程管理 ──
uv run orange launch --port 8720          # 一键启动全部进程
uv run orange server --port 8720          # 仅启动消息总线
uv run orange agent trace_agent --server-url http://127.0.0.1:8720
uv run orange agent frida_agent --server-url http://127.0.0.1:8720
uv run orange agent network_agent --server-url http://127.0.0.1:8720

# ── 命令行 ──
uv run orange send "@trace_agent 分析签名算法"
uv run orange log --from trace_agent --limit 10
uv run orange log --type conclusion
uv run orange tasks --limit 10
uv run orange memory --task-id <task_id>
uv run orange evidence --task-id <task_id>
uv run orange tools --task-id <task_id>
uv run orange skills                        # 查看所有技能
uv run orange skills --search ssl           # 搜索技能
uv run orange handoffs --task-id <task_id>
uv run orange steps --run-id <run_id>
uv run orange context --session-id <session_id> --task-id <task_id> --query "X-Sign"
uv run orange cleanup --max-memories-per-task 100
uv run orange eval

# ── curl 调试 ──
curl http://127.0.0.1:8720/api/v1/history
curl http://127.0.0.1:8720/api/v1/health
```

## 配置

通过 `.env` 配置（所有变量带 `ORANGEAGENT_` 前缀）：

```bash
# LLM
OPENAI_API_KEY=sk-xxx
ORANGEAGENT_LITELLM_MODEL=openai/deepseek-chat

# 总线
ORANGEAGENT_BUS_TRANSPORT=local           # local | http
ORANGEAGENT_BUS_SERVER_PORT=8720

# Trace 文件
ORANGEAGENT_TRACE_CODE_FILE=/path/to/code.log
ORANGEAGENT_TRACE_RW_FILE=/path/to/rw.log
ORANGEAGENT_TRACE_BL_FILE=/path/to/bl.log

# JADX
ORANGEAGENT_JADX_HOST=127.0.0.1
ORANGEAGENT_JADX_PORT=8650
```

## Bus Server API

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/v1/publish` | POST | 发布消息 |
| `/api/v1/history` | GET | 查询历史 (`?from=&type=&limit=`) |
| `/api/v1/tasks` | GET | 查询任务运行状态 |
| `/api/v1/memories` | GET/POST | 查询或写入 agent 记忆 |
| `/api/v1/evidence` | GET | 查询任务证据 |
| `/api/v1/tool-calls` | GET/POST | 查询或写入工具调用审计 |
| `/api/v1/handoffs` | GET/POST | 查询或写入结构化 agent 委托 |
| `/api/v1/run-steps` | GET/POST | 查询或写入 run step 执行审计 |
| `/api/v1/context` | GET | 预览按权重选择的记忆上下文 |
| `/api/v1/runtime/cleanup` | POST | 归档过量低价值 tentative 记忆 |
| `/api/v1/health` | GET | 健康检查 |
| `/ws?agent_id=<id>` | WS | Agent 连接 |
| `/ws?role=observer` | WS | 观察者（TUI） |

## Runtime 记忆模型

OrangeAgent 会为请求自动生成 `session_id`、`task_id`、`run_id`，并把结论中的证据沉淀为结构化记录：

- `tasks`：记录任务目标、负责人、阶段和状态
- `evidence`：记录 trace 行号、JADX 引用、工具结果等可定位证据
- `memories`：记录 agent 结论，按 `verified`、`tentative`、`rejected` 等状态和权重排序
- `tool_calls`：记录工具名、参数、耗时、错误、截断状态和结果摘要
- `handoffs`：记录 agent 间委托目标、原因、期望输出、必需证据和允许工具域
- `run_steps`：记录 LLM、tool、handoff、checkpoint 等执行步骤，支持按 `run_id` 复盘
- `context`：按任务、证据强度、来源、置信度和相关性选择注入给 agent 的上下文

默认采用混合型记忆策略：工具/用户确认的证据高权重，agent 猜测以 `tentative` 低权重保留，被推翻的结论标记为 `rejected`，只作为禁止依据提醒。
`orange cleanup` 会按任务保留高权重 tentative 记忆，并把超出的低价值记录归档，避免长期运行后上下文被旧猜测污染。
`orange eval` 会基于任务、证据、handoff、运行步骤和记忆记录给 runtime 完整度打分，用于快速发现协作链路断点。

## 新特性（v0.2+）

### 工具自注册（ToolRegistry）

工具通过 `@tool` 装饰器注册到全局注册表，Agent 按 toolset 自动发现：

```python
from orangeagent.tools.registry import tool, get_definitions

@tool(name="trace_search", toolset="trace", description="在 trace 文件中搜索")
async def trace_search(query: str, file: str, limit: int) -> str:
    ...

# Agent 自动发现工具
tools = get_definitions("frida")  # → 6 个 Frida 工具的 OpenAI schema
```

向后兼容：旧 executor 模式仍可正常使用，46 个工具在启动时自动注册。

### 中间件管道（Middleware Pipeline）

在工具调用前后插入拦截点，支持参数改写、拦截、审计：

```python
from orangeagent.runtime.middleware import inject_context_middleware

pipeline = MiddlewarePipeline()
pipeline.use(inject_context_middleware(device_id="usb-001"))

# 也可以用装饰器
@pipeline.on_tool_request
def audit(name, args):
    logger.info("tool_call", name=name)
    return args
```

默认启用审计中间件，记录所有工具调用的入参出参。

### 技能系统（Skill Store）

将逆向经验沉淀为可检索、可复用的 YAML 步骤模板：

```bash
orange skills              # 查看所有技能
orange skills --search ssl # 搜索技能
```

技能存放在 `data/skills/` 目录，自动匹配 Agent 当前场景注入 system prompt。
Frida Agent 启动时自动注入 SSL Pinning 绕过步骤、VMP 脱壳流程等匹配技能。

### 结构化事件体系

单一 `Event` 类 + 工厂函数，避免 dataclass 继承的字段顺序问题：

```python
from orangeagent.runtime.event import agent_status_event, tool_call_event

sink.emit(agent_status_event(agent_id="frida", state="thinking"))
sink.emit(tool_call_event(agent_id="frida", tool_name="frida_hook_method", ...))
```

内置 7 种工厂函数覆盖 Agent 状态、LLM 调用、工具调用、缓存诊断、消息、记忆、中间件场景。

## 运行测试

```bash
uv run pytest tests/ -v                 # 全量测试（171 个）
uv run pytest tests/test_bus.py -v      # 消息总线
uv run pytest tests/test_server.py -v   # FastAPI 服务端
uv run pytest tests/test_new_components.py -v  # 新组件（registry/middleware/skill_store）
```

## 项目结构

```
src/orangeagent/
├── agents/         # Agent 实现（9 个 Agent）
├── bus/            # 消息总线（ABC + Local + HTTP）
├── cli/            # typer CLI + Textual TUI
├── processes/      # 多进程入口
├── runtime/        # 事件系统 + 中间件 + 技能系统 + 记忆模型
├── server/         # FastAPI 总线服务端
├── tools/          # 工具执行器 + ToolRegistry 自注册
├── verify/         # 自校验系统
├── config.py       # pydantic-settings 配置
├── launcher.py     # 多进程启动器
└── eval/           # runtime 评估
data/skills/        # 技能定义（YAML 格式）
```

## 技术栈

Python 3.12+ · litellm · FastAPI · uvicorn · httpx · websockets · Textual · SQLite · aiosqlite · typer · structlog · Pydantic v2 · uv

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

### 多进程模式

```
bus-server (FastAPI :8720)  ←── HTTP + WebSocket
     ↑
     ├── main-agent      协调、路由
     ├── network-agent   网络流量分析、签名定位
     ├── ida-jadx-agent  APK 静态反编译
     ├── trace-agent     ARM64 指令级 trace
     ├── frida-agent     运行时 Hook
     ├── apktool-agent   APK 解包/重打包
     ├── js-reverse-agent JS 逆向
     ├── ida-agent       Native 分析
     ├── unidbg-agent    SO 模拟执行
     └── tui             Textual 终端界面
```

也支持单进程模式（`orange run`）——所有 Agent 在同一 asyncio 进程内通信，适合开发调试。

### Agent 一览

| Agent | 职责 | 工具数 | 覆盖层 |
|-------|------|--------|--------|
| **MainAgent** | 协调、拆解任务、路由 | 0 | 管理层 |
| **NetworkAgent** | 网络流量分析、签名定位 | 2 | L1 黑盒观测 |
| **IdaJadxAgent** | APK 静态代码反编译 | 11 | L2 Java 静态 |
| **FridaAgent** | 运行时 Hook、类枚举 | 6 | L3 Java Hook |
| **ApktoolAgent** | APK 解包、Smali 修改、重打包 | 4 | L4 Smali |
| **JsReverseAgent** | WebView JS 反混淆、格式化 | 3 | L2 WebView |
| **IdaAgent** | Native 二进制深度分析 | 5 | L6 Native |
| **TraceAgent** | ARM64 指令级 trace 分析 | 3 | L10 trace |
| **UnidbgAgent** | Native SO 模拟执行、算法复现 | 2 | L10-L11 算法 |

> 全部 **42 个工具** 通过 ToolRegistry 自注册，10 个 toolset 按 Agent 自动匹配。

### 通信机制

Agent 通过 `@agent_id` 互相点名，平权路由，不需要中心调度器：

```
Human: "@trace_agent 分析签名"            → trace_agent
trace_agent: "发现 HMAC, @ida_jadx_agent" → ida_jadx_agent
ida_jadx_agent: "确认了, @trace_agent"    → trace_agent
trace_agent: "结论: HMAC-SHA256"          → human
```

- `request` / `question` 触发 Agent 动作
- `conclusion` / `decision` 仅通知不触发
- `status` 不持久化，仅 UI 更新

---

## 核心概念

### 发现循环（Discovery Loop）

逆向工程不是线性步骤，而是**假设驱动的探索循环**。OrangeAgent 围绕这个循环设计：

```
     Observe ──→ Hypothesize ──→ Test ──→ Verify / Reject ──→ Pivot
         ↑                                                     │
         └───────────────────── ← ─────────────────────────────┘
```

| 阶段 | 做什么 | 工具 |
|------|--------|------|
| **Observe** | 搜索 APK、看入口、搜特征 | `trace_search`, `jadx_search_classes_by_keyword` |
| **Hypothesize** | 创建猜想 | `hypothesis_create` |
| **Test** | 验证猜想 | `frida_hook_method`, `@trace_agent` 等 |
| **Verify** | 确认结论 | `hypothesis_verify` |
| **Reject** | 标记 dead end | `hypothesis_reject`, `hypothesis_check_dead_end` |

### 技能系统

逆向经验沉淀为可检索的技能，Agent 自动匹配注入 system prompt。

**两种格式：**

```yaml
# 1. YAML 格式（简单场景）
name: bypass-ssl-pinning
tags: [ssl, network, hook]
steps:
  - tool: frida_bypass_ssl_pinning
  - tool: jadx_search_classes_by_keyword
    args: { search_term: TrustManager }
```

```json
// 2. manifest 格式（推荐，支持触发条件和 Markdown 指令）
{
  "name": "discovery-loop",
  "priority": 5,
  "entry": "SKILL.md",
  "triggers": {
    "commands": ["/explore"],
    "patterns": ["不知道从哪下手", "没有头绪"]
  }
}
```

**技能匹配（Kun 风格评分）：**

| 匹配方式 | 分数 | 说明 |
|---------|------|------|
| 显式提及 `@name` / `$name` | 1000 + priority | 最精确 |
| 命令前缀 `/cmd` | 900 + priority | 用户主动触发 |
| 关键词匹配 | 500 + priority | 自动关联 |
| 标签匹配 | 300 + priority | 兜底匹配 |

**已内置 6 个技能：**

```
data/skills/
├── discovery-loop/          # 发现循环方法论（元技能）
├── signature-analysis/      # 签名算法定位与还原
├── algorithm-recovery/      # 加密算法识别（含常量速查）
├── packer-identification/   # 壳/加固识别与应对
├── bypass-ssl-pinning/      # SSL Pinning 绕过
└── vmp-dump-assist/         # VMP 脱壳辅助
```

每个技能包含 **Stance 章节**（✅适合 / ❌不适合），Agent 不会乱用。

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

旧 executor 模式完全向后兼容。

### 中间件管道

在工具调用前后插入拦截点，默认启用：

```python
from orangeagent.runtime.middleware import inject_context_middleware

pipeline = MiddlewarePipeline()
pipeline.use(inject_context_middleware(device_id="usb-001"))

@pipeline.on_tool_request
def audit(name, args):
    logger.info("tool_call", name=name)
    return args
```

| 中间件 | 默认启用 | 作用 |
|--------|---------|------|
| **audit** | ✅ | 记录所有工具调用的入参出参和耗时 |
| **storm_breaker** | ✅ | 抑制重复工具调用（滑动窗口，阈值 3/8） |

StormBreaker 在逆向场景中尤其有用：Agent 经常对 trace 或 JADX 反复搜索相似内容，StormBreaker 自动拦截重复调用，节省大量 token。

### 假设追踪（5 个工具）

发现循环的基础设施，Agent 可在对话中管理探索过程：

```
hypothesis_create(description="可能是 AES-128-CBC", tags="aes")
  → 返回假设 ID

hypothesis_verify(hypothesis_id="1", evidence="trace 确认 AES 指令")
  → 标记为已确认

hypothesis_reject(hypothesis_id="1", reason="未发现 AES 指令")
  → 标记为 dead end

hypothesis_list(status="active")
  → 列出所有活跃假设

hypothesis_check_dead_end(description="AES-128-CBC")
  → 检查是否重复踩坑
```

`load_skill` 工具让 Agent 可在对话中动态加载任意技能指令。

---

## CLI 命令

```bash
# ── TUI 交互 ──
uv run orange run                         # 单进程 TUI
uv run orange run --transport http        # 多进程 TUI

# ── 多进程管理 ──
uv run orange launch --port 8720          # 一键启动全部进程
uv run orange server --port 8720          # 仅启动消息总线
uv run orange agent main_agent --server-url http://127.0.0.1:8720

# ── 消息与历史 ──
uv run orange send "@trace_agent 分析签名"
uv run orange log --from trace_agent --limit 10
uv run orange log --type conclusion

# ── 任务与审计 ──
uv run orange tasks --limit 10
uv run orange tools --task-id <task_id>
uv run orange handoffs --task-id <task_id>
uv run orange steps --run-id <run_id>
uv run orange context --session-id <sid> --task-id <tid> --query "X-Sign"

# ── 记忆与证据 ──
uv run orange memory --task-id <task_id>
uv run orange evidence --task-id <task_id>
uv run orange cleanup --max-memories-per-task 100

# ── 技能 ──
uv run orange skills                      # 查看所有技能
uv run orange skills --search ssl         # 按关键词搜索
# 技能也通过 @skill_name 在对话中触发

# ── 评估 ──
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

# Trace 文件（trace_agent 需要）
ORANGEAGENT_TRACE_CODE_FILE=/path/to/code.log
ORANGEAGENT_TRACE_RW_FILE=/path/to/rw.log
ORANGEAGENT_TRACE_BL_FILE=/path/to/bl.log

# JADX（ida_jadx_agent 需要）
ORANGEAGENT_JADX_HOST=127.0.0.1
ORANGEAGENT_JADX_PORT=8650
```

## Bus Server API

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/v1/publish` | POST | 发布消息 |
| `/api/v1/history` | GET | 查询历史 |
| `/api/v1/tasks` | GET | 任务运行状态 |
| `/api/v1/memories` | GET/POST | Agent 记忆 |
| `/api/v1/evidence` | GET | 任务证据 |
| `/api/v1/tool-calls` | GET/POST | 工具调用审计 |
| `/api/v1/handoffs` | GET/POST | Agent 委托记录 |
| `/api/v1/run-steps` | GET/POST | 执行步骤审计 |
| `/api/v1/context` | GET | 记忆上下文预览 |
| `/api/v1/runtime/cleanup` | POST | 归档低价值记忆 |
| `/api/v1/health` | GET | 健康检查 |
| `/ws?agent_id=<id>` | WS | Agent 连接 |
| `/ws?role=observer` | WS | 观察者（TUI） |

## Runtime 记忆模型

| 记录 | 用途 |
|------|------|
| `tasks` | 任务目标、负责人、阶段和状态 |
| `evidence` | trace 行号、JADX 引用、工具结果 |
| `memories` | 结论，按 `verified` / `tentative` / `rejected` 排序 |
| `tool_calls` | 工具名、参数、耗时、错误、截断 |
| `handoffs` | Agent 间委托记录 |
| `run_steps` | LLM / tool / checkpoint 执行步骤 |

`orange cleanup` 按任务保留高权重记忆并归档低价值记录。
`orange eval` 对 runtime 完整度打分，发现协作链路断点。

## 运行测试

```bash
uv run pytest tests/ -v                          # 全量 171 个
uv run pytest tests/test_bus.py -v               # 消息总线
uv run pytest tests/test_server.py -v            # FastAPI 服务端
uv run pytest tests/test_new_components.py -v    # 新组件（registry/middleware/skill）
```

## 项目结构

```
src/orangeagent/
├── agents/         # 9 个 Agent（平权协作）
├── bus/            # 消息总线（ABC + Local + HTTP）
├── cli/            # typer CLI + Textual TUI
│   └── tui/        # Textual widgets
├── processes/      # 多进程启动入口
├── runtime/        # 事件 / 中间件 / 技能 / 记忆 / 存储
│   ├── event.py          # 单 Event + 7 工厂函数
│   ├── middleware.py     # 中间件 Pipeline + ToolStormBreaker
│   └── skill_store.py   # SkillStore + 评分匹配 + manifest
├── server/         # FastAPI 总线（WebSocket + REST）
├── tools/          # 执行器 + ToolRegistry + 假设追踪
│   ├── registry.py       # @tool 装饰器 + get_definitions()
│   ├── hypothesis_tools.py  # 5 个假设追踪工具
│   └── skill_loader.py   # load_skill 动态加载
├── verify/         # 自校验
├── config.py       # 配置
├── launcher.py     # 多进程启动器
└── eval/           # runtime 评分
data/skills/        # 6 个逆向技能（manifest 格式）
tests/              # 171 个测试
```

## 技术栈

Python 3.12+ · litellm · FastAPI · uvicorn · httpx · websockets
Textual · SQLite / aiosqlite · typer · structlog · Pydantic v2 · uv

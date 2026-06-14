# OrangeAgent — Android 逆向 Multi-Agent 系统

## 项目概述

多 Agent 协作系统，用于 Android 逆向工程。Agent 平权——通过 `@agent_id` 互相点名，不设中心路由。
每个 Agent 工具集隔离，只能调自己领域内的工具。

**核心范式**：Observe → Hypothesize → Test → Verify → Pivot 发现循环。

**代码量**：~9,900 行 Python · 65 文件 · 189 测试

## 技术栈

- **语言**：Python 3.12+
- **LLM**：litellm（统一接口，切模型只改配置）
- **消息总线**：MessageBus ABC → LocalMessageBus（SQLite + asyncio.Queue）+ HttpMessageBus（HTTP + WebSocket）
- **服务端**：FastAPI + uvicorn（独立进程）
- **CLI**：typer + Textual TUI
- **Trace**：ak_search（C daemon，mmap + 行索引）
- **JADX**：HTTP 直连 JADX Java Plugin（127.0.0.1:8650）
- **包管理**：uv

## 架构

### 9 个 Agent

| Agent | agent_id | 工具集 | 允许工具 | 职责 |
|-------|----------|--------|---------|------|
| **MainAgent** | main_agent | 无限制 | 全部 | 协调、路由、拆解任务 |
| **TraceAgent** | trace_agent | trace | 3 | ARM64 指令级 trace |
| **IdaJadxAgent** | ida_jadx_agent | jadx | 11 | JADX 静态反编译 |
| **FridaAgent** | frida_agent | frida | 6 | 运行时 Hook |
| **NetworkAgent** | network_agent | network | 2 | 流量分析、签名定位 |
| **ApktoolAgent** | apktool_agent | apktool | 4 | APK 解包/重打包 |
| **JsReverseAgent** | js_reverse_agent | js_reverse | 3 | JS 逆向、反混淆 |
| **IdaAgent** | ida_agent | ida | 5 | IDA Native 分析 |
| **UnidbgAgent** | unidbg_agent | unidbg | 2 | SO 模拟执行 |

Agent 跨工具集调用被中间件拦截，返回错误提示给 LLM。

### @mention 路由（平权）

```
Human: "@trace_agent 分析签名"            → trace_agent
trace_agent: "发现 HMAC, @ida_jadx_agent" → ida_jadx_agent
ida_jadx_agent: "确认了, @trace_agent"    → trace_agent
trace_agent: "结论: HMAC-SHA256"          → human
```

- `request` / `question` 触发 Agent 动作
- `conclusion` / `decision` 仅通知不触发
- `status` 不持久化，仅 TUI 更新

### 运行模式

```
# 单进程（开发/测试）
uv run orange run

# 多进程（生产）
uv run orange launch --port 8720
```

多进程架构：

```
bus-server (FastAPI :8720)  ←── HTTP POST + WebSocket
     ↑
     ├── main_agent / trace_agent / frida_agent / ...
     └── tui (Textual 终端)
```

### 目录结构

```
src/orangeagent/
├── agents/         # 9 个 Agent（BaseAgent → 各子类）
├── bus/            # 消息总线（ABC + Local + HTTP）
├── cli/            # typer CLI + Textual TUI
├── processes/      # 多进程入口
├── runtime/        # 事件 / 中间件 / 技能 / 记忆 / 存储
│   ├── event.py          # Event 类 + 7 工厂函数
│   ├── middleware.py     # Pipeline + audit + storm_breaker
│   └── skill_store.py   # SkillStore + 评分匹配
├── server/         # FastAPI 总线（REST + WebSocket）
├── tools/          # 执行器 + ToolRegistry + 假设追踪
│   ├── registry.py       # @tool 装饰器
│   ├── hypothesis_tools.py  # 5 个假设追踪工具
│   └── skill_loader.py   # load_skill 动态加载
├── verify/         # 自校验
├── launcher.py     # 多进程启动器
├── config.py       # pydantic-settings
└── eval/           # runtime 评分
data/skills/        # 6 个技能（manifest + Stance）
prompts/            # Agent system prompt（markdown）
tests/              # 189 个测试
```

## ToolRegistry（工具自注册）

工具通过 `@tool` 装饰器注册，Agent 按 toolset 自动发现：

```python
from orangeagent.tools.registry import tool, get_definitions

@tool(name="trace_search", toolset="trace", description="在 trace 中搜索")
async def trace_search(query: str, file: str, limit: int) -> str:
    ...

tools = get_definitions("frida")  # 6 个工具
```

**现有 42 个工具 · 10 个 toolset**：
trace / jadx / frida / network / apktool / js_reverse / ida / unidbg / hypothesis / skill

旧 executor 模式完全向后兼容。

## 中间件 Pipeline

默认启用两个中间件：

| 中间件 | 作用 | 拦截点 |
|--------|------|--------|
| **audit_middleware** | 审计日志（入参/出参/耗时） | tool_response |
| **storm_breaker_middleware** | 抑制重复调用（窗 8 阈 3） | tool_request |

StormBreaker 在逆向场景中尤其有价值——Agent 经常对 trace/JADX 反复搜索相似内容。

可扩展：
```python
@pipeline.on_tool_request
def inject_context(name, args):
    args.setdefault("device_id", "usb")
    return args
```

## 技能系统

6 个逆向技能，按 Kun 风格评分匹配自动注入。

### 匹配算法

| 方式 | 分数 | 说明 |
|------|------|------|
| 显式提及 `@name` | 1000 + priority | 最精确 |
| 命令前缀 `/cmd` | 900 + priority | 主动触发 |
| 关键词 | 500 + priority | 自动关联 |
| 标签 | 300 + priority | 兜底 |

### 技能列表

```
discovery-loop/       # 发现循环方法论（元技能）
signature-analysis/   # 签名定位 + 假设追踪步骤
algorithm-recovery/   # AES/SM4/RSA 常量速查
packer-identification/# 9 种壳特征对照表
bypass-ssl-pinning/   # SSL Pinning 绕过
vmp-dump-assist/      # VMP 脱壳辅助
```

每个技能有 Stance 章节明确边界（✅适合 / ❌不适合）。

### 两种格式

```json
// manifest 格式（推荐）
data/skills/<name>/skill.json + SKILL.md
```

```yaml
# YAML 格式（兼容）
data/skills/<name>.yaml
```

Agent 对话中可通过 `load_skill` 工具动态加载技能指令。

## 假设追踪（发现循环）

逆向的 Obverse → Hypothesize → Test → Verify → Pivot 循环的基础设施：

```
hypothesis_create(description="可能是 AES-128-CBC", tags="aes")
  → UUID 假设 ID

hypothesis_verify(hypothesis_id="<id>", evidence="trace 确认 AES 指令")
  → ✅ 标记已验证

hypothesis_reject(hypothesis_id="<id>", reason="未发现 AES 指令")
  → ❌ 标记 dead end

hypothesis_list(status="active")

hypothesis_check_dead_end(description="AES-128-CBC")
  → ⚠️ 以防重复踩坑
```

按 session 隔离存储，互不污染。

## 事件系统

单一 Event 类 + 7 工厂函数，避免 dataclass 继承问题：

```python
from orangeagent.runtime.event import agent_status_event, tool_call_event

sink.emit(agent_status_event(agent_id="frida", state="thinking"))
sink.emit(tool_call_event(agent_id="frida", tool_name="frida_hook_method", ...))
```

## 运行测试

```bash
uv run pytest tests/ -v                   # 全量 189
uv run pytest tests/test_new_components.py -v  # 新组件
```

## 关键设计原则

- **Agent 零耦合**，只通过消息总线通信
- **bus 消息 ≠ LLM 上下文**，每条消息独立
- **Agent 只响应 request/question**，conclusion 里被 @ 只是 CC
- **工具集隔离**，FridaAgent 不能调 network 工具
- **发现循环**优先于线性执行，假设追踪是核心
- **宁可上报人，不让错误结论通过**
- **不要过度设计**，先跑通再迭代

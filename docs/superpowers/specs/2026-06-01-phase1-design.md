# Phase 1 设计文档：消息总线 + 双 Agent + CLI + 自校验

## 概述

实现 Android 逆向 Multi-Agent 系统的最小可用版本。单进程 asyncio 架构，两个 agent（主 Agent + Trace Agent）通过消息总线通信，用户通过单窗口 CLI 交互。

## 架构

```
┌─────────────────────────────────────┐
│  单进程 (asyncio)                    │
│                                     │
│  CLI ←→ 主Agent ←→ 消息总线 ←→ Trace Agent │
│                    (SQLite)          │
└─────────────────────────────────────┘
```

- 所有 agent 是 asyncio 协程，逻辑隔离
- 消息总线是唯一通信通道
- 模型调用通过 litellm 统一接口

## 模块一：消息总线

### 数据模型

```python
class Message(BaseModel):
    id: str                          # uuid4
    from_agent: str                  # 发送者 ID ("human", "main_agent", "trace_agent")
    to_agent: str | None             # None = 广播
    type: Literal["conclusion", "request", "question", "decision"]
    content: str
    evidence: list[str]              # 支撑依据
    confidence: Literal["high", "medium", "low"]
    timestamp: datetime
    reply_to: str | None             # 回复哪条消息的 ID
```

### 接口

```python
class MessageBus:
    def __init__(self, db_path: Path)
    async def publish(msg: Message) -> None
    async def subscribe(agent_id: str) -> AsyncIterator[Message]
    async def get_history(
        limit: int = 50,
        from_agent: str | None = None,
        msg_type: str | None = None,
    ) -> list[Message]
```

### 存储

- SQLite 单文件，位于项目目录 `.duckagent/messages.db`
- 一张 messages 表，字段对应 Message 模型
- 启动时自动建表（如不存在）
- 消息不可变，不支持修改和删除

### 分发机制

- 每个 agent 订阅时创建一个 asyncio.Queue
- publish 时：私信放目标 agent 队列，广播复制到所有队列（除发送者）
- subscribe 返回 async iterator，从队列中 yield 消息

## 模块二：Agent 基类

```python
class BaseAgent:
    agent_id: str
    system_prompt: str
    context: list[dict]              # 私有对话历史
    bus: MessageBus

    async def start() -> None
    async def stop() -> None
    async def on_message(msg: Message) -> None
    async def send(
        to: str | None,
        content: str,
        type: str = "conclusion",
        evidence: list[str] | None = None,
        confidence: str = "high",
        reply_to: str | None = None,
    ) -> None
    async def think(input: str) -> str
```

### 生命周期

1. `start()`: 加载 system_prompt → 订阅消息总线 → 进入消息循环
2. 消息循环: 从 subscribe iterator 取消息 → 调 `on_message()`
3. `on_message()`: 子类实现具体逻辑
4. `think()`: 构建 messages 列表，调 litellm.acompletion()
5. `send()`: 结论类消息过自校验 → 通过 bus.publish() 发出
6. `stop()`: 取消订阅，清理资源

### 上下文管理

- context 只包含该 agent 自己的交互（收到的消息 + 模型回复）
- 收到消息时追加到 context（作为 user message）
- 模型回复追加到 context（作为 assistant message）
- system_prompt 从 `prompts/{agent_id}.md` 文件加载

## 模块三：主 Agent (MainAgent)

### 职责

- 接收用户实时输入
- 加载 AGENT.md 作为项目上下文
- 拆解用户指令为具体子任务
- 分发给对应 agent
- 综合多个 agent 结论回复用户

### 特殊行为

- 启动时读取 AGENT.md，内容注入 system_prompt 尾部
- 用户消息通过 CLI 传入，包装成 Message(from="human") 发到总线
- 收到消息后 think()：判断自己处理还是转发
- 转发时不是原样转，而是拆解成具体问题
- 拿不准的 send(to="human") 上报

### 不做的事

- 不汇报进度
- 不替代人做最终决策
- 不在没有依据时下结论

## 模块四：Trace Agent (TraceAgent)

### 职责

接收 trace 分析请求，读取 trace 数据，输出带证据的结论。

### 输入格式

多文件 trace 结构（具体格式待用户提供）：
- 汇编文件
- 内存读写文件
- PLT 跳转文件

Phase 1 先按通用结构实现，后续适配真实格式。

### 行为约束（写进 system_prompt）

- 每个断言必须引用具体 trace 行号作为证据
- 不确定的标 confidence: "low"
- 推理链每一步都要有 trace 中的依据
- 看不出来就说看不出来，不编造

### 处理流程

1. 收到 type="request" 的消息
2. 从消息内容中获取 trace 数据或文件路径
3. 读取 trace 数据
4. think(): 分析算法、数据流、handler 语义
5. send(): 输出 conclusion，附带 evidence

## 模块五：CLI

### 命令

```
duck run                              # 启动系统
duck send "消息内容"                   # 发消息给主 Agent（非交互模式）
duck log                              # 查看消息历史
duck log --from trace_agent --limit 10  # 过滤查看
duck stop                             # 停止系统
```

### 交互模式

`duck run` 启动后进入交互模式：
- 直接输入文字 = 发给主 Agent
- @human 的消息实时显示
- Ctrl+C 退出

### 显示格式

```
[14:01] trace_agent → all: 识别到循环结构，疑似轮函数
[14:03] trace_agent → main_agent: AES-128-CBC，IV 在 r2
[14:05] main_agent → you: 分析完成，trace 中包含 AES-128-CBC 加密...

> 你的输入在这里
```

### 实现

- 用 asyncio 同时监听用户输入和消息推送
- 入口命令用 click 或 typer
- 单窗口，不依赖 tmux

## 模块六：自校验

### 位置

嵌在 `BaseAgent.send()` 中，发送前自动执行。只对 type="conclusion" 的消息生效。

### 第一层：硬校验

规则检查，不调模型：
- evidence 字段不能为空列表
- confidence 必须是 "high"/"medium"/"low"
- 如果引用了行号，检查行号是否在 trace 数据范围内（如有 trace 上下文）

### 第二层：模型自查

- 把结论 + evidence 重新喂给模型
- prompt: "审视这个推理链，有没有逻辑漏洞或证据不足的地方？"
- 如果发现问题：打回，重新 think()
- 最多重试 3 次，超过上报 human

### 配置

- 自校验可通过配置开关（开发调试时可关闭）
- 重试上限可配置，默认 3 次

## 目录结构

```
duckagent/
├── src/
│   └── duckagent/
│       ├── __init__.py
│       ├── bus/
│       │   ├── __init__.py
│       │   ├── models.py          # Message 数据模型
│       │   └── store.py           # SQLite 存储 + 消息分发
│       ├── agents/
│       │   ├── __init__.py
│       │   ├── base.py            # BaseAgent
│       │   ├── main_agent.py      # MainAgent
│       │   └── trace_agent.py     # TraceAgent
│       ├── verify/
│       │   ├── __init__.py
│       │   ├── hard.py            # 硬校验
│       │   └── self_check.py      # 模型自查
│       ├── cli/
│       │   ├── __init__.py
│       │   └── app.py             # CLI 入口和命令
│       └── config.py              # 配置管理
├── prompts/
│   ├── main_agent.md              # 主 Agent system prompt
│   └── trace_agent.md             # Trace Agent system prompt
├── tests/
├── data/                          # 测试用 trace 数据
├── AGENT.md                       # 项目任务简报（用户编写）
├── pyproject.toml
└── README.md
```

## 依赖

```
litellm          # 模型调用
pydantic >= 2.0  # 数据模型
aiosqlite        # 异步 SQLite
typer            # CLI 框架
structlog        # 日志
python-dotenv    # 环境变量
```

## 不在 Phase 1 范围内

- tmux 多窗格布局
- 独立校验 agent（Phase 2）
- 其他 agent：IDA、Unidbg（Phase 3）
- MCP 工具集成（Phase 3）
- FastAPI HTTP 接口（需要多进程时再加）
- 持久化项目状态管理（Phase 3）

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from orangeagent.agents.base import BaseAgent
from orangeagent.bus import LocalMessageBus, Message
from orangeagent.bus.http_client import HttpMessageBus


@pytest.mark.asyncio
async def test_http_bus_reader_drops_oldest_when_queue_is_full():
    bus = HttpMessageBus(server_url="http://test:8720", queue_maxsize=1)
    queue = bus.subscribe("main_agent")

    first = Message(from_agent="human", to_agent="main_agent", type="request", content="第一条")
    second = Message(from_agent="human", to_agent="main_agent", type="request", content="第二条")

    class FakeWebSocket:
        async def __aiter__(self):
            for msg in (first, second):
                yield '{"type": "message", "data": ' + msg.model_dump_json() + "}"

    bus._ws = FakeWebSocket()
    await bus._ws_reader()

    received = await asyncio.wait_for(queue.get(), timeout=1.0)
    assert received.content == "第二条"
    assert queue.empty()


@pytest.mark.asyncio
async def test_malformed_tool_arguments_are_audited_instead_of_crashing(tmp_path):
    bus = LocalMessageBus(db_path=tmp_path / "bad_tool.db")
    await bus.initialize()
    try:
        task = await bus.create_task(
            session_id="s1",
            title="坏工具参数",
            owner_agent="trace_agent",
            goal="审计坏参数",
        )
        agent = BaseAgent(
            agent_id="trace_agent",
            system_prompt="你是 Trace Agent。",
            bus=bus,
            model="test-model",
            verify_enabled=False,
        )

        tool_call = MagicMock()
        tool_call.id = "call-1"
        tool_call.function.name = "trace_search"
        tool_call.function.arguments = "{bad json"

        first = MagicMock()
        first.choices = [MagicMock()]
        first.choices[0].message.content = ""
        first.choices[0].message.tool_calls = [tool_call]

        second = MagicMock()
        second.choices = [MagicMock()]
        second.choices[0].message.content = "已处理"
        second.choices[0].message.tool_calls = None

        with patch(
            "orangeagent.agents.base.litellm.acompletion",
            new=AsyncMock(side_effect=[first, second]),
        ):
            result = await agent.think(
                "搜索",
                tools=[{"type": "function", "function": {"name": "trace_search"}}],
                tool_executor=object(),
                session_id="s1",
                task_id=task.id,
            )

        records = await bus.get_tool_calls(task_id=task.id)
        assert result == "已处理"
        assert records[0].status == "error"
        assert "JSON" in (records[0].error or "")
    finally:
        await bus.close()


@pytest.mark.asyncio
async def test_internal_agent_conclusion_does_not_complete_task(tmp_path):
    bus = LocalMessageBus(db_path=tmp_path / "task_status.db")
    await bus.initialize()
    try:
        request = Message(from_agent="human", to_agent="main_agent", type="request", content="分析")
        await bus.publish(request)
        await bus.publish(
            Message(
                session_id=request.session_id,
                task_id=request.task_id,
                from_agent="trace_agent",
                to_agent="main_agent",
                type="conclusion",
                content="trace line 1 初步显示 HMAC",
                evidence=["line 1: hmac"],
                confidence="medium",
                reply_to=request.id,
            )
        )

        tasks = await bus.get_tasks(session_id=request.session_id)
        assert tasks[0].status == "running"
        assert tasks[0].phase == "agent_conclusion"
    finally:
        await bus.close()


def test_storm_breaker_handles_unhashable_args():
    """_freeze_args 对 list/dict 参数不再崩溃，storm_breaker 仍能抑制重复调用。"""
    from orangeagent.runtime.middleware import ToolStormBreaker

    breaker = ToolStormBreaker(window_size=5, threshold=2)
    args = {"classes": ["a", "b"], "opts": {"deep": True}}
    # 第一次不抑制，第二次达到阈值抑制——关键是不抛 TypeError
    assert breaker.check("frida_bypass", args) is False
    assert breaker.check("frida_bypass", args) is True


def test_storm_breaker_same_complex_args_compare_equal():
    """内容相同的复杂参数应被视为同一签名（序列化稳定）。"""
    from orangeagent.runtime.middleware import ToolStormBreaker

    breaker = ToolStormBreaker(window_size=5, threshold=2)
    # dict key 顺序不同但内容相同，应判定为重复
    breaker.check("tool_x", {"opts": {"a": 1, "b": 2}})
    assert breaker.check("tool_x", {"opts": {"b": 2, "a": 1}}) is True


def test_compact_context_preserves_tool_call_pairing():
    """压缩后不留下无配对的孤儿 tool 消息（会触发 LLM API 协议错误）。"""
    agent = BaseAgent(
        agent_id="trace_agent",
        system_prompt="sys",
        bus=LocalMessageBus(db_path=":memory:"),
        model="test-model",
        verify_enabled=False,
    )
    # 构造：system + user + 大量 assistant[tool_calls]/tool 配对
    context = [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "q"},
    ]
    for i in range(40):
        context.append({"role": "assistant", "content": None,
                        "tool_calls": [{"id": f"c{i}"}]})
        context.append({"role": "tool", "tool_call_id": f"c{i}",
                        "name": "t", "content": "r"})

    agent._last_compact_len = 0
    agent._maybe_compact_context(context)

    # 压缩后第一条 tool 消息前必须有 assistant，且无孤儿 tool
    for idx, msg in enumerate(context):
        if msg.get("role") == "tool":
            assert idx > 0 and context[idx - 1].get("role") in ("assistant", "tool"), \
                f"位置 {idx} 的 tool 消息前缺少 assistant"


@pytest.mark.asyncio
async def test_ws_reconnect_does_not_evict_new_connection():
    """同一 agent 重连后，旧连接断开不应踢掉新连接。"""
    from orangeagent.server.ws_manager import ConnectionManager

    class FakeWS:
        def __init__(self):
            self.closed = False
        async def accept(self):
            pass
        async def close(self):
            self.closed = True

    mgr = ConnectionManager()
    old_ws, new_ws = FakeWS(), FakeWS()

    await mgr.connect_agent(old_ws, "trace_agent")
    await mgr.connect_agent(new_ws, "trace_agent")  # 重连：顶替旧连接
    assert old_ws.closed is True                     # 旧 ws 被主动关闭

    # 旧连接的 finally 触发：按身份校验，不应删掉新连接
    mgr.disconnect_agent("trace_agent", old_ws)
    assert mgr._agents.get("trace_agent") is new_ws

    # 新连接自己断开才真正移除
    mgr.disconnect_agent("trace_agent", new_ws)
    assert "trace_agent" not in mgr._agents


def test_guardrails_allows_each_agent_own_domain_tools():
    """六类专精 agent 必须能调用自身领域工具（早期 bug:未登记即拒绝把它们全锁死）。"""
    import orangeagent.tools  # noqa: F401  触发工具注册
    from orangeagent.runtime.guardrails import check_tool_policy

    cases = [
        ("frida_agent", "frida_hook_method"),
        ("network_agent", "network_make_request"),
        ("apktool_agent", "apktool_decode"),
        ("ida_agent", "ida_decompile"),
        ("unidbg_agent", "unidbg_run"),
        ("js_reverse_agent", "js_format"),
        ("trace_agent", "trace_search"),
        ("ida_jadx_agent", "jadx_get_strings"),
    ]
    for agent_id, tool in cases:
        d = check_tool_policy(agent_id=agent_id, tool_name=tool, arguments={})
        assert d.allowed, f"{agent_id} 应能调用 {tool}，却被拒: {d.reason}"


def test_guardrails_blocks_cross_domain_and_destructive():
    """域隔离与危险操作拦截仍生效。"""
    import orangeagent.tools  # noqa: F401
    from orangeagent.runtime.guardrails import check_tool_policy

    # 越界：frida_agent 调 trace 工具
    crossed = check_tool_policy(agent_id="frida_agent", tool_name="trace_search", arguments={})
    assert crossed.allowed is False

    # 公共域：任何 agent 都可用 hypothesis
    common = check_tool_policy(agent_id="frida_agent", tool_name="hypothesis_create", arguments={})
    assert common.allowed is True

    # 危险参数被拦
    risky = check_tool_policy(
        agent_id="frida_agent", tool_name="frida_hook_method", arguments={"x": "rm -rf /"},
    )
    assert risky.allowed is False

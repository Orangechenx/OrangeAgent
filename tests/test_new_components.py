"""测试：Registry / Middleware / SkillStore 新组件"""

import json
from pathlib import Path

import pytest
import yaml

from orangeagent.tools.registry import (
    ToolDef, register, tool, get, get_definitions,
    execute, list_toolsets, clear,
)
from orangeagent.runtime.middleware import (
    MiddlewarePipeline, MiddlewareHandler, MiddlewareResult,
    audit_middleware, inject_context_middleware, ToolStormBreaker,
)
from orangeagent.runtime.event import Event
from orangeagent.runtime.skill_store import SkillStore, SkillDef


# ═══════════════════════════════════════════════════════════════
# Registry 测试
# ═══════════════════════════════════════════════════════════════

class TestRegistry:
    """工具注册表自注册模式测试"""

    def setup_method(self) -> None:
        # 备份全局 registry 真实内容：这些测试会 clear() 全局单例，
        # 若不在 teardown 还原，会污染后续依赖 registry 的测试（如 guardrails 域解析）
        from orangeagent.tools import registry as _reg
        self._registry_backup = dict(_reg._tools)
        clear()

    def teardown_method(self) -> None:
        from orangeagent.tools import registry as _reg
        _reg._tools.clear()
        _reg._tools.update(self._registry_backup)

    def test_register_and_get(self):
        """register() + get() 基本功能"""
        register("test_tool", "test", "测试工具",
                 {"type": "object", "properties": {"x": {"type": "string"}}},
                 handler=lambda x: f"hello {x}")
        td = get("test_tool")
        assert td is not None
        assert td.name == "test_tool"
        assert td.toolset == "test"
        assert td.description == "测试工具"
        assert td.handler is not None

    def test_register_without_handler(self):
        """向后兼容：无 handler 的注册（executor 模式）"""
        register("exec_tool", "legacy", "旧模式工具",
                 {"type": "object", "properties": {}})
        td = get("exec_tool")
        assert td is not None
        assert td.handler is None
        # 无 handler 时 execute 返回错误
        result = json.loads(execute("exec_tool", {}))
        assert result["status"] == "error"

    def test_get_unknown(self):
        """查询不存在工具返回 None"""
        assert get("nope") is None

    def test_get_definitions_returns_openai_schema(self):
        """get_definitions 返回 OpenAI function-calling 格式"""
        register("a_tool", "alpha", "阿尔法测试",
                 {"type": "object", "properties": {"p": {"type": "string"}}})
        defs = get_definitions("alpha")
        assert len(defs) == 1
        assert defs[0]["type"] == "function"
        assert defs[0]["function"]["name"] == "a_tool"
        assert defs[0]["function"]["parameters"]["properties"]["p"]["type"] == "string"

    def test_get_definitions_filters_by_toolset(self):
        """get_definitions 按 toolset 过滤"""
        register("tool_a", "set1", "描述", {"type": "object", "properties": {}})
        register("tool_b", "set2", "描述", {"type": "object", "properties": {}})
        assert len(get_definitions("set1")) == 1
        assert len(get_definitions("set2")) == 1
        assert len(get_definitions()) == 2

    def test_tool_decorator(self):
        """@tool 装饰器注册函数为工具"""
        @tool(name="ping", toolset="net", description="ping 测试")
        def ping(target: str, count: int = 3) -> str:
            return f"ping {target} x{count}"

        td = get("ping")
        assert td is not None
        assert td.handler is not None
        # 通过 handler 执行
        result = td.handler("localhost", 5)
        assert result == "ping localhost x5"

    def test_tool_decorator_infers_params(self):
        """@tool 装饰器自动推断参数 schema"""
        @tool(name="search", toolset="db", description="搜索")
        def search(query: str, limit: int = 10) -> list:
            return [query, limit]

        defs = get_definitions("db")
        params = defs[0]["function"]["parameters"]
        assert "query" in params["properties"]
        assert params["properties"]["query"]["type"] == "string"
        assert params["required"] == ["query"]

    def test_execute_with_handler(self):
        """execute() 通过 handler 执行工具"""
        register("double", "math", "翻倍", {"type": "object", "properties": {"n": {"type": "integer"}}},
                 handler=lambda n: str(n * 2))
        result = execute("double", {"n": 21})
        assert result == "42"

    def test_execute_unknown(self):
        """execute() 未知工具返回错误"""
        result = json.loads(execute("unknown", {}))
        assert result["status"] == "error"

    def test_list_toolsets(self):
        """list_toolsets 返回所有工具集名称"""
        register("x", "set_a", "", {"type": "object", "properties": {}})
        register("y", "set_b", "", {"type": "object", "properties": {}})
        register("z", "set_a", "", {"type": "object", "properties": {}})
        toolsets = list_toolsets()
        assert "set_a" in toolsets
        assert "set_b" in toolsets
        assert len(toolsets) == 2

    def test_clear(self):
        """clear 清空注册表"""
        register("tmp", "test", "", {"type": "object", "properties": {}})
        assert get("tmp") is not None
        clear()
        assert get("tmp") is None


# ═══════════════════════════════════════════════════════════════
# Middleware 测试
# ═══════════════════════════════════════════════════════════════

class TestMiddleware:
    """中间件管道测试"""

    def test_pipeline_use(self):
        """注册中间件"""
        pipeline = MiddlewarePipeline()
        handler = MiddlewareHandler("test", request_handler=lambda n, a: a)
        pipeline.use(handler)
        assert len(pipeline.handlers) == 1

    def test_tool_request_allowed(self):
        """tool_request 允许通过"""
        pipeline = MiddlewarePipeline()
        @pipeline.on_tool_request
        def noop(name, args):
            return args

        result = pipeline.on_tool_call_request("test", {"x": 1})
        assert result.allowed
        assert result.modified_args == {"x": 1}

    def test_tool_request_modify_args(self):
        """tool_request 改写参数"""
        pipeline = MiddlewarePipeline()
        @pipeline.on_tool_request
        def inject(name, args):
            args["device_id"] = "usb"
            return args

        result = pipeline.on_tool_call_request("test", {})
        assert result.modified_args.get("device_id") == "usb"

    def test_tool_request_block(self):
        """tool_request 阻止调用"""
        pipeline = MiddlewarePipeline()
        @pipeline.on_tool_request
        def blocker(name, args):
            return None

        result = pipeline.on_tool_call_request("test", {})
        assert not result.allowed
        assert "阻止" in result.reason

    def test_tool_response_modify(self):
        """tool_response 改写结果"""
        pipeline = MiddlewarePipeline()
        @pipeline.on_tool_response
        def wrap(name, args, result, ms):
            return f"[wrapped] {result}"

        modified = pipeline.on_tool_call_response("test", {}, "hello", 100)
        assert modified == "[wrapped] hello"

    def test_tool_response_passthrough(self):
        """tool_response 返回 None 不修改结果"""
        pipeline = MiddlewarePipeline()
        @pipeline.on_tool_response
        def noop(name, args, result, ms):
            return None

        modified = pipeline.on_tool_call_response("test", {}, "hello", 100)
        assert modified == "hello"

    def test_remove_handler(self):
        """按名称移除中间件"""
        pipeline = MiddlewarePipeline()
        pipeline.use(MiddlewareHandler("mw1", request_handler=lambda n, a: a))
        pipeline.use(MiddlewareHandler("mw2", request_handler=lambda n, a: a))
        assert len(pipeline.handlers) == 2
        pipeline.remove("mw1")
        assert len(pipeline.handlers) == 1
        assert pipeline.handlers[0].name == "mw2"

    def test_clear(self):
        """清空所有中间件"""
        pipeline = MiddlewarePipeline()
        pipeline.use(MiddlewareHandler("mw", request_handler=lambda n, a: a))
        pipeline.clear()
        assert len(pipeline.handlers) == 0

    def test_on_tool_request_decorator(self):
        """on_tool_request 装饰器注册"""
        pipeline = MiddlewarePipeline()
        @pipeline.on_tool_request(name="my_mw")
        def handler(name, args):
            return args
        assert len(pipeline.handlers) == 1
        assert pipeline.handlers[0].name == "my_mw"

    def test_handler_disabled(self):
        """禁用的中间件不生效"""
        pipeline = MiddlewarePipeline()
        handler = MiddlewareHandler("blocker",
            request_handler=lambda n, a: None,  # 会阻止
            enabled=False,  # 但禁用了
        )
        pipeline.use(handler)
        result = pipeline.on_tool_call_request("test", {"ok": 1})
        assert result.allowed  # 禁用了所以不阻止

    def test_middleware_chain_order(self):
        """多个中间件按注册顺序执行"""
        pipeline = MiddlewarePipeline()
        calls = []

        @pipeline.on_tool_request
        def first(name, args):
            calls.append("first")
            return args

        @pipeline.on_tool_request
        def second(name, args):
            calls.append("second")
            return args

        pipeline.on_tool_call_request("test", {})
        assert calls == ["first", "second"]

    def test_audit_middleware(self):
        """审计中间件在 tool_response 时发射事件"""
        events: list[Event] = []
        from orangeagent.runtime.event import CallbackSink
        sink = CallbackSink()
        sink.subscribe(events.append)

        pipeline = MiddlewarePipeline(sink=sink)
        pipeline.use(audit_middleware(sink=sink))
        pipeline.on_tool_call_response("test_tool", {"x": 1}, "ok", 50)
        assert len(events) >= 1
        assert events[0].kind.value == "tool_call"

    def test_inject_context_middleware(self):
        """上下文注入中间件自动加参数"""
        pipeline = MiddlewarePipeline()
        pipeline.use(inject_context_middleware(device_id="usb-001"))

        result = pipeline.on_tool_call_request("test", {"cmd": "list"})
        assert result.modified_args["cmd"] == "list"
        assert result.modified_args["device_id"] == "usb-001"

    def test_inject_context_does_not_override(self):
        """上下文注入不覆盖已有参数"""
        pipeline = MiddlewarePipeline()
        pipeline.use(inject_context_middleware(device_id="usb-001"))

        result = pipeline.on_tool_call_request("test", {"device_id": "custom"})
        assert result.modified_args["device_id"] == "custom"


# ═══════════════════════════════════════════════════════════════
# SkillStore 测试
# ═══════════════════════════════════════════════════════════════

class TestSkillStore:
    """技能存储测试"""

    def test_skill_def_matches(self):
        """SkillDef.matches 标签匹配"""
        s = SkillDef(name="test", tags=["ssl", "hook"])
        assert s.matches(tags=["ssl"])
        assert s.matches(tags=["hook", "ssl"])
        assert not s.matches(tags=["vmp"])

    def test_skill_def_matches_applies_to(self):
        """SkillDef.matches 场景匹配"""
        s = SkillDef(name="test", tags=["ssl"], applies_to=["android"])
        assert s.matches(tags=["ssl"], applies_to="android")
        assert not s.matches(tags=["ssl"], applies_to="ios")

    def test_skill_def_matches_empty_tags(self):
        """空标签列表总是匹配"""
        s = SkillDef(name="test", tags=["ssl"])
        assert s.matches(tags=[])
        assert s.matches()

    def test_load_from_yaml(self, tmp_path):
        """从 YAML 加载技能"""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        f = skills_dir / "test-skill.yaml"
        f.write_text(yaml.dump({
            "name": "test-skill",
            "description": "测试",
            "tags": ["test", "demo"],
            "steps": [{"tool": "ping", "description": "ping"}],
        }))

        store = SkillStore(skills_dir)
        store.load_all()
        assert store.count == 1
        s = store.get("test-skill")
        assert s is not None
        assert s.description == "测试"
        assert len(s.steps) == 1

    def test_load_skips_non_yaml(self, tmp_path):
        """非 yaml 文件被跳过"""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        (skills_dir / "readme.txt").write_text("not a skill")
        (skills_dir / "data.json").write_text("{}")

        store = SkillStore(skills_dir)
        store.load_all()
        assert store.count == 0

    def test_search_by_name(self, tmp_path):
        """按名称搜索"""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        store = SkillStore(skills_dir)
        skill = SkillDef(name="ssl-bypass", description="bypass SSL",
                         tags=["ssl"], steps=[])
        store._skills["ssl-bypass"] = skill
        results = store.search("ssl")
        assert len(results) == 1
        assert results[0].name == "ssl-bypass"

    def test_search_by_tag(self, tmp_path):
        """按标签搜索"""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        store = SkillStore(skills_dir)
        store._skills["a"] = SkillDef(name="skill-a", tags=["hook", "frida"])
        store._skills["b"] = SkillDef(name="skill-b", tags=["vmp", "脱壳"])
        results = store.search("frida")
        assert len(results) == 1

    def test_search_empty_query_returns_all(self, tmp_path):
        """空搜索返回全部"""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        store = SkillStore(skills_dir)
        store._skills["a"] = SkillDef(name="a", tags=[])
        store._skills["b"] = SkillDef(name="b", tags=[])
        assert len(store.search("")) == 2

    def test_find_by_tags(self, tmp_path):
        """按标签精准匹配"""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        store = SkillStore(skills_dir)
        store._skills["ssl"] = SkillDef(name="ssl", tags=["ssl", "hook"])
        store._skills["vmp"] = SkillDef(name="vmp", tags=["vmp"])
        matched = store.find_by_tags(["ssl"])
        assert len(matched) == 1
        assert matched[0].name == "ssl"

    def test_list_all(self, tmp_path):
        """列出所有技能"""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        store = SkillStore(skills_dir)
        store._skills["a"] = SkillDef(name="a", tags=[])
        store._skills["b"] = SkillDef(name="b", tags=[])
        assert len(store.list_all()) == 2

    def test_load_from_nonexistent_dir(self, tmp_path):
        """不存在的目录不报错"""
        store = SkillStore(tmp_path / "nonexistent")
        loaded = store.load_all()
        assert loaded == []

    def test_to_dict(self):
        """SkillDef 序列化"""
        s = SkillDef(name="test", description="desc", tags=["a"],
                     steps=[{"tool": "x"}], source_file="/path/to/skill.yaml")
        d = s.to_dict()
        assert d["name"] == "test"
        assert d["tags"] == ["a"]
        assert d["steps"] == [{"tool": "x"}]
        assert d["source_file"] == "/path/to/skill.yaml"

    def test_resolve_turn_keyword_match(self, tmp_path):
        """resolve_turn 关键词评分匹配"""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        store = SkillStore(skills_dir)
        store._skills["ssl-bypass"] = SkillDef(
            name="ssl-bypass", description="SSL Pinning bypass",
            tags=["ssl", "hook"], priority=10,
        )
        store._skills["vmp"] = SkillDef(
            name="vmp", description="VMP dump", tags=["vmp"],
        )
        res = store.resolve_turn("ssl pinning 绕过", tags=["ssl"])
        names = [m.skill.name for m in res.active]
        assert "ssl-bypass" in names

    def test_catalog_instruction(self, tmp_path):
        """catalog_instruction 生成技能目录"""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        store = SkillStore(skills_dir)
        store._skills["test"] = SkillDef(name="test", description="测试技能", tags=["test"])
        catalog = store.catalog_instruction(budget=2000)
        assert "test" in catalog
        assert "测试技能" in catalog

    def test_resolve_turn_explicit_mention(self, tmp_path):
        """显式提及 @name 最高分"""
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        store = SkillStore(skills_dir)
        store._skills["scan"] = SkillDef(name="scan", description="scan", priority=0)
        res = store.resolve_turn("用 @scan 分析")
        assert any(m.skill.name == "scan" and m.score >= 1000 for m in res.active)

    def test_skill_instruction_text_with_entry(self, tmp_path):
        """instruction_text 返回 Markdown 内容"""
        s = SkillDef(name="test", description="test", entry_content="# 测试指令\n\n步骤1", steps=[{"tool": "x"}])
        text = s.instruction_text()
        assert "# 测试指令" in text
        assert "步骤1" in text

    def test_skill_instruction_text_fallback(self, tmp_path):
        """无 entry_content 时回退到 steps"""
        s = SkillDef(name="test", description="test", steps=[{"tool": "x", "description": "do x"}])
        text = s.instruction_text()
        assert "do x" in text


# ═══════════════════════════════════════════════════════════════
# Hypothesis 工具测试
# ═══════════════════════════════════════════════════════════════

class TestHypothesisTools:
    """假设追踪 5 工具测试"""

    def test_create_and_verify(self):
        """创建假设 → 验证通过"""
        import json
        from orangeagent.tools.hypothesis_tools import hypothesis_create, hypothesis_verify
        r1 = json.loads(hypothesis_create(description="可能是 AES-128", tags="aes,cbc"))
        hid = r1["hypothesis_id"]
        r2 = json.loads(hypothesis_verify(hypothesis_id=hid, evidence="trace 确认 AES 指令"))
        assert r2["status"] == "ok"

    def test_create_and_reject(self):
        """创建假设 → 拒绝 + dead end"""
        import json
        from orangeagent.tools.hypothesis_tools import hypothesis_create, hypothesis_reject, hypothesis_check_dead_end
        r1 = json.loads(hypothesis_create(description="可能是 MD5", tags="md5"))
        hid = r1["hypothesis_id"]
        r2 = json.loads(hypothesis_reject(hypothesis_id=hid, reason="不是 MD5"))
        assert r2["status"] == "ok"
        r3 = json.loads(hypothesis_check_dead_end(description="可能是 MD5"))
        assert r3["is_dead_end"]

    def test_list_by_status(self):
        """按状态过滤假设"""
        import json
        from orangeagent.tools.hypothesis_tools import hypothesis_create, hypothesis_verify, hypothesis_list
        r1 = json.loads(hypothesis_create(description="H1", tags=""))
        r2 = json.loads(hypothesis_create(description="H2", tags=""))
        json.loads(hypothesis_verify(hypothesis_id=r2["hypothesis_id"], evidence="ok"))
        all_h = json.loads(hypothesis_list(status="all"))
        assert all_h["count"] >= 2

    def test_check_dead_end_no_match(self):
        """不存在的 dead end 返回未发现"""
        import json
        from orangeagent.tools.hypothesis_tools import hypothesis_check_dead_end
        r = json.loads(hypothesis_check_dead_end(description="RSA 加密"))
        assert not r["is_dead_end"]

    def test_invalid_hypothesis(self):
        """验证不存在的假设返回错误"""
        from orangeagent.tools.hypothesis_tools import hypothesis_verify
        r = hypothesis_verify(hypothesis_id="999", evidence="test")
        assert "error" in r


# ═══════════════════════════════════════════════════════════════
# ToolStormBreaker 测试
# ═══════════════════════════════════════════════════════════════

class TestStormBreaker:
    """工具风暴抑制器测试"""

    def test_suppress_repeated_calls(self):
        """重复相同调用达到阈值后抑制"""
        breaker = ToolStormBreaker(window_size=5, threshold=3)
        for i in range(4):
            suppressed = breaker.check("trace_search", {"query": "AES"})
        assert suppressed  # 第 4 次应被抑制

    def test_different_args_not_suppressed(self):
        """不同参数不被抑制"""
        breaker = ToolStormBreaker(window_size=5, threshold=3)
        for i in range(4):
            suppressed = breaker.check("trace_search", {"query": f"query_{i}"})
        assert not suppressed

    def test_reset_clears_window(self):
        """reset 清空窗口"""
        breaker = ToolStormBreaker(window_size=5, threshold=2)
        breaker.check("tool", {"x": 1})
        breaker.check("tool", {"x": 1})
        breaker.reset()
        # reset 后应该重新计数
        r = breaker.check("tool", {"x": 1})
        assert not r

    def test_exempt_tools_not_suppressed(self):
        """豁免工具不受抑制"""
        breaker = ToolStormBreaker(window_size=5, threshold=2,
                                    exempt_tools={"hypothesis_create"})
        for i in range(5):
            suppressed = breaker.check("hypothesis_create", {"description": "test"})
        assert not suppressed

    def test_below_threshold_not_suppressed(self):
        """未达阈值不抑制"""
        breaker = ToolStormBreaker(window_size=10, threshold=5)
        for i in range(3):
            r = breaker.check("tool", {"x": 1})
        assert not r


# ═══════════════════════════════════════════════════════════════
# skill_loader 测试
# ═══════════════════════════════════════════════════════════════

class TestSkillLoader:
    """load_skill 工具测试"""

    def test_load_skill_uninitialized(self):
        """未初始化时返回错误"""
        from orangeagent.tools.skill_loader import _load_skill
        r = _load_skill("test")
        assert "未初始化" in r or "error" in r

    def test_load_skill_not_found(self, tmp_path):
        """加载不存在的技能返回错误"""
        from orangeagent.runtime.skill_store import SkillStore
        from orangeagent.tools.skill_loader import _load_skill, set_skill_store
        store = SkillStore(tmp_path / "skills")
        set_skill_store(store)
        r = _load_skill("nonexistent")
        assert "不存在" in r or "error" in r

    def test_load_skill_success(self, tmp_path):
        """成功加载技能"""
        from orangeagent.runtime.skill_store import SkillDef
        from orangeagent.tools.skill_loader import _load_skill, set_skill_store
        store = SkillStore(tmp_path / "skills")
        store._skills["test"] = SkillDef(name="test", description="测试", steps=[{"tool": "x"}])
        set_skill_store(store)
        r = _load_skill("test")
        assert "ok" in r or "测试" in r

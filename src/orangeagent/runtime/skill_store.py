"""技能系统（参考 Kun SkillRuntime + Hermes skills 设计）。

技能 = 可复用的逆向步骤模板，支持两种格式：

1. YAML 格式（原有，向后兼容）:
    data/skills/bypass-ssl-pinning.yaml

2. manifest 格式（Kun 风格，推荐）:
    data/skills/my-skill/
    ├── skill.json        # 清单：名称、触发条件、入口文件
    └── SKILL.md          # 技能指令（Markdown）

匹配算法（Kun 风格评分）:
  - 显式提及 ($name / @name)  → 1000 + priority
  - 命令前缀（如 /review）    → 900 + priority
  - 关键词模式匹配            → 500 + priority
  - 标签匹配                  → 300 + priority
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import structlog
import yaml

logger = structlog.get_logger()


# ── 技能定义 ──────────────────────────────────────────────────


class SkillDef:
    """技能定义（内存表示）。"""

    def __init__(
        self,
        name: str,
        description: str = "",
        applies_to: list[str] | None = None,
        tags: list[str] | None = None,
        steps: list[dict[str, Any]] | None = None,
        source_file: str | None = None,
        # Kun 风格扩展字段
        triggers: dict[str, list[str]] | None = None,
        priority: int = 0,
        allowed_tools: list[str] | None = None,
        entry_content: str | None = None,
    ) -> None:
        self.name = name
        self.description = description
        self.applies_to = applies_to or []
        self.tags = tags or []
        self.steps = steps or []
        self.source_file = source_file or ""
        # Kun 风格扩展
        self.triggers = triggers or {"commands": [], "patterns": [], "file_types": []}
        self.priority = priority
        self.allowed_tools = allowed_tools or []
        self.entry_content = entry_content or ""  # 完整技能指令文本

    def matches(self, tags: list[str] | None = None, applies_to: str | None = None) -> bool:
        """检查技能是否匹配给定的标签和场景。"""
        if tags and not any(t in self.tags for t in tags):
            return False
        if applies_to and self.applies_to and applies_to not in self.applies_to:
            return False
        return True

    def match_score(self, prompt: str, tags: list[str] | None = None) -> int:
        """Kun 风格评分匹配。返回匹配分数，0 表示不匹配。

        分数越高匹配度越高：
          显式提及: 1000 + priority
          命令前缀:  900 + priority
          关键词:     500 + priority
          标签:       300 + priority
        """
        p_lower = prompt.lower()
        n_lower = self.name.lower()

        # 1. 显式提及 ($name / @name)
        if f"${n_lower}" in p_lower or f"@{n_lower}" in p_lower:
            return 1000 + self.priority

        # 2. 命令前缀 /name
        for cmd in self.triggers.get("commands", []):
            if p_lower.startswith(cmd.lower()):
                return 900 + self.priority

        # 3. 关键词模式匹配
        for pattern in self.triggers.get("patterns", []):
            try:
                if re.search(pattern, p_lower):
                    return 500 + self.priority
            except re.error:
                continue
        # 同时也匹配描述中的关键词
        if self.description and any(w in p_lower for w in self.description.lower().split()[:5]):
            return 500 + self.priority

        # 4. 标签匹配
        if tags and any(t in self.tags for t in tags):
            return 300 + self.priority

        return 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "applies_to": self.applies_to,
            "tags": self.tags,
            "steps": self.steps,
            "triggers": self.triggers,
            "priority": self.priority,
            "allowed_tools": self.allowed_tools,
            "source_file": self.source_file,
        }

    def instruction_text(self, max_chars: int = 4000) -> str:
        """返回格式化后的技能指令文本（注入 system prompt 用）。"""
        lines = [f"## 技能: {self.name}"]
        if self.description:
            lines.append(f"  描述: {self.description}")
        if self.tags:
            lines.append(f"  标签: {', '.join(self.tags)}")

        # 优先用完整的 Markdown 指令
        if self.entry_content:
            content = self.entry_content
            if len(content) > max_chars:
                content = content[:max_chars] + "\n…[截断]"
            lines.append(content)
            return "\n".join(lines)

        # 回退到 YAML steps 格式
        lines.append("  步骤:")
        for step in self.steps[:6]:
            tool = step.get("tool", "?")
            desc = step.get("description", "")
            lines.append(f"    - `{tool}`: {desc}")
        if len(self.steps) > 6:
            lines.append(f"    - …还有 {len(self.steps) - 6} 步")
        return "\n".join(lines)

    def __repr__(self) -> str:
        return f"SkillDef(name={self.name!r}, tags={self.tags})"


# ── 匹配结果 ──────────────────────────────────────────────────


class SkillMatch:
    """一次技能匹配的结果。"""
    def __init__(self, skill: SkillDef, score: int, reason: str) -> None:
        self.skill = skill
        self.score = score
        self.reason = reason


class TurnSkillResolution:
    """一次 turn 的技能解析结果（参考 Kun SkillTurnResolution）。"""
    def __init__(
        self,
        active: list[SkillMatch],
        catalog: str = "",
        instructions: list[str] | None = None,
    ) -> None:
        self.active = active
        self.catalog = catalog
        self.instructions = instructions or []

    @property
    def injected_bytes(self) -> int:
        return sum(len(i.encode("utf-8")) for i in self.instructions)


# ── 技能存储 ──────────────────────────────────────────────────


class SkillStore:
    """技能存储：支持 YAML 和 manifest (skill.json) 两种格式。"""

    def __init__(self, skills_dir: str | Path | None = None) -> None:
        self._skills: dict[str, SkillDef] = {}
        self._skills_dir = Path(skills_dir or self._default_skills_dir())

    @staticmethod
    def _default_skills_dir() -> Path:
        candidates = [
            Path.cwd() / "data" / "skills",
            Path(__file__).resolve().parents[2] / "data" / "skills",
        ]
        for c in candidates:
            if c.is_dir():
                return c
        return candidates[0]

    # ── 加载 ──────────────────────────────────────────────

    def load_all(self) -> list[SkillDef]:
        """加载所有技能（YAML + manifest 两种格式）。"""
        self._skills.clear()
        if not self._skills_dir.is_dir():
            logger.warning("skills_dir_not_found", path=str(self._skills_dir))
            return []

        loaded: list[SkillDef] = []

        # 1. 扫描 manifest 格式（skill.json 目录）
        for entry in sorted(self._skills_dir.iterdir()):
            if entry.is_dir():
                skill = self._load_manifest(entry)
                if skill:
                    self._skills[skill.name] = skill
                    loaded.append(skill)

        # 2. 扫描 YAML 格式（.yaml / .yml 文件）
        for fpath in sorted(self._skills_dir.iterdir()):
            if fpath.suffix not in (".yaml", ".yml"):
                continue
            if fpath.name in (".yaml", ".yml"):
                continue
            try:
                skill = self._load_yaml(fpath)
                if skill and skill.name not in self._skills:
                    self._skills[skill.name] = skill
                    loaded.append(skill)
            except Exception as exc:
                logger.warning("skill_load_failed", file=str(fpath), error=str(exc))

        logger.info("skills_loaded", count=len(loaded), directory=str(self._skills_dir))
        return loaded

    def _load_yaml(self, fpath: Path) -> SkillDef | None:
        """加载单个 YAML 技能文件。"""
        raw = yaml.safe_load(fpath.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return None
        return SkillDef(
            name=str(raw.get("name", fpath.stem)),
            description=str(raw.get("description", "")),
            applies_to=raw.get("applies_to", []),
            tags=raw.get("tags", []),
            steps=raw.get("steps", []),
            triggers=raw.get("triggers", {}),
            priority=raw.get("priority", 0),
            allowed_tools=raw.get("allowed_tools", []),
            source_file=str(fpath),
        )

    def _load_manifest(self, dir_path: Path) -> SkillDef | None:
        """从目录加载 manifest 格式技能（skill.json + 入口文件）。"""
        manifest_path = dir_path / "skill.json"
        if not manifest_path.exists():
            return None

        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

        name = str(manifest.get("name", dir_path.stem))
        entry_file = manifest.get("entry", "SKILL.md")
        entry_path = dir_path / entry_file

        entry_content = ""
        if entry_path.exists():
            entry_content = entry_path.read_text(encoding="utf-8")

        return SkillDef(
            name=name,
            description=str(manifest.get("description", "")),
            tags=manifest.get("tags", []),
            steps=[],  # manifest 格式用 entry_content 代替 steps
            triggers={
                "commands": manifest.get("triggers", {}).get("commands", []),
                "patterns": manifest.get("triggers", {}).get("patterns", []),
                "file_types": manifest.get("triggers", {}).get("file_types", []),
            },
            priority=manifest.get("priority", 0),
            allowed_tools=manifest.get("allowed_tools", []),
            entry_content=entry_content,
            source_file=str(manifest_path),
        )

    # ── 查询 ──────────────────────────────────────────────

    def get(self, name: str) -> SkillDef | None:
        """按名称获取技能。"""
        return self._skills.get(name)

    def search(self, query: str) -> list[SkillDef]:
        """按关键词搜索技能（名称/描述/标签/步骤）。"""
        q = query.lower()
        results: list[SkillDef] = []
        for skill in self._skills.values():
            if (q in skill.name.lower()
                    or q in skill.description.lower()
                    or any(q in t.lower() for t in skill.tags)
                    or any(q in str(s).lower() for s in skill.steps)):
                results.append(skill)
        return results

    def find_by_tags(self, tags: list[str], applies_to: str | None = None) -> list[SkillDef]:
        """按标签和场景匹配技能。"""
        return [s for s in self._skills.values() if s.matches(tags=tags, applies_to=applies_to)]

    # ── Kun 风格评分匹配 ─────────────────────────────────

    def resolve_turn(
        self,
        prompt: str,
        tags: list[str] | None = None,
        active_limit: int = 3,
        instruction_budget: int = 12000,
        catalog_budget: int = 4000,
    ) -> TurnSkillResolution:
        """解析一次 turn，返回匹配的技能列表（Kun 风格评分排序）。"""
        if not self._skills:
            return TurnSkillResolution(active=[])

        # 1. 对所有技能评分
        scored: list[SkillMatch] = []
        for skill in self._skills.values():
            score = skill.match_score(prompt, tags=tags)
            if score > 0:
                scored.append(SkillMatch(
                    skill=skill,
                    score=score,
                    reason=self._match_reason(score),
                ))

        # 2. 按分数降序排列，取 top active_limit
        scored.sort(key=lambda m: (-m.score, m.skill.name))
        active = scored[:active_limit]

        # 3. 构建指令注入（受 budget 限制）
        instructions: list[str] = []
        budget_remaining = instruction_budget
        for match in active:
            text = match.skill.instruction_text(max_chars=budget_remaining)
            text_bytes = len(text.encode("utf-8"))
            if text_bytes <= budget_remaining:
                instructions.append(text)
                budget_remaining -= text_bytes
            else:
                break

        # 4. 构建目录
        catalog = self._build_catalog(budget=catalog_budget)

        return TurnSkillResolution(
            active=active,
            catalog=catalog,
            instructions=instructions,
        )

    def catalog_instruction(self, budget: int = 4000) -> str:
        """返回可用技能目录（注入 system prompt 用，参考 Kun catalogInstruction）。"""
        return self._build_catalog(budget=budget)

    def _build_catalog(self, budget: int = 4000) -> str:
        """构建技能目录文本。"""
        if not self._skills:
            return ""
        lines = ["## 📋 可用技能", "使用 @skill_name 或 $skill_name 引用技能："]
        for skill in sorted(self._skills.values(), key=lambda s: s.name):
            entry = f"\n- **{skill.name}**: {skill.description or '无描述'}"
            if skill.tags:
                entry += f" [{', '.join(skill.tags[:3])}]"
            entry_bytes = len(entry.encode("utf-8"))
            # 估算总字节，超过 budget 就截断
            current_total = sum(len(l.encode("utf-8")) for l in lines)
            if current_total + entry_bytes > budget:
                lines.append("\n…以及更多技能（用 `orange skills` 查看）")
                break
            lines.append(entry)
        return "\n".join(lines)

    @staticmethod
    def _match_reason(score: int) -> str:
        if score >= 1000:
            return "explicit_mention"
        if score >= 900:
            return "command_prefix"
        if score >= 500:
            return "keyword_match"
        return "tag_match"

    def list_all(self) -> list[SkillDef]:
        """列出所有已加载的技能。"""
        return list(self._skills.values())

    @property
    def count(self) -> int:
        return len(self._skills)

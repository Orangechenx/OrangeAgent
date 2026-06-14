"""轻量技能系统（参考 Hermes skills 设计）。

技能 = 可复用的逆向步骤模板，YAML 格式存储。
用于将逆向经验沉淀为可检索、可复用的步骤指南。

技能格式 (YAML):
    name: bypass-ssl-pinning
    description: 通用 SSL Pinning 绕过流程
    applies_to: [android]
    tags: [ssl, network, hook]
    steps:
      - tool: frida_bypass_ssl_pinning
        description: 使用 Frida 通用绕过
      - tool: jadx_search_classes_by_keyword
        args: { search_term: TrustManager }
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import structlog
import yaml

logger = structlog.get_logger()


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
    ) -> None:
        self.name = name
        self.description = description
        self.applies_to = applies_to or []
        self.tags = tags or []
        self.steps = steps or []
        self.source_file = source_file or ""

    def matches(self, tags: list[str] | None = None, applies_to: str | None = None) -> bool:
        """检查技能是否匹配给定的标签和场景。"""
        if tags and not any(t in self.tags for t in tags):
            return False
        if applies_to and self.applies_to and applies_to not in self.applies_to:
            return False
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "applies_to": self.applies_to,
            "tags": self.tags,
            "steps": self.steps,
            "source_file": self.source_file,
        }

    def __repr__(self) -> str:
        return f"SkillDef(name={self.name!r}, tags={self.tags})"


class SkillStore:
    """技能存储：从 YAML 文件加载、检索、匹配技能。"""

    def __init__(self, skills_dir: str | Path | None = None) -> None:
        self._skills: dict[str, SkillDef] = {}
        self._skills_dir = Path(skills_dir or self._default_skills_dir())

    @staticmethod
    def _default_skills_dir() -> Path:
        """默认技能目录：项目根目录下的 data/skills/"""
        # 尝试从项目根目录定位
        candidates = [
            Path.cwd() / "data" / "skills",
            Path(__file__).resolve().parents[2] / "data" / "skills",
        ]
        for c in candidates:
            if c.is_dir():
                return c
        # 不存在则返回第一个候选路径
        return candidates[0]

    def load_all(self) -> list[SkillDef]:
        """加载 skills_dir 下所有 .yaml/.yml 技能文件。"""
        self._skills.clear()
        if not self._skills_dir.is_dir():
            logger.warning("skills_dir_not_found", path=str(self._skills_dir))
            return []

        loaded: list[SkillDef] = []
        for fpath in sorted(self._skills_dir.iterdir()):
            if fpath.suffix not in (".yaml", ".yml"):
                continue
            try:
                skill = self._load_file(fpath)
                if skill:
                    self._skills[skill.name] = skill
                    loaded.append(skill)
            except Exception as exc:
                logger.warning("skill_load_failed", file=str(fpath), error=str(exc))

        logger.info("skills_loaded", count=len(loaded), directory=str(self._skills_dir))
        return loaded

    def _load_file(self, fpath: Path) -> SkillDef | None:
        """加载单个技能 YAML 文件。"""
        raw = yaml.safe_load(fpath.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return None
        return SkillDef(
            name=str(raw.get("name", fpath.stem)),
            description=str(raw.get("description", "")),
            applies_to=raw.get("applies_to", []),
            tags=raw.get("tags", []),
            steps=raw.get("steps", []),
            source_file=str(fpath),
        )

    def get(self, name: str) -> SkillDef | None:
        """按名称获取技能。"""
        return self._skills.get(name)

    def search(self, query: str) -> list[SkillDef]:
        """按关键词搜索技能（名称/描述/标签）。"""
        q = query.lower()
        results: list[SkillDef] = []
        for skill in self._skills.values():
            if (q in skill.name.lower()
                    or q in skill.description.lower()
                    or any(q in t.lower() for t in skill.tags)):
                results.append(skill)
        return results

    def find_by_tags(self, tags: list[str], applies_to: str | None = None) -> list[SkillDef]:
        """按标签和场景匹配技能。"""
        return [s for s in self._skills.values() if s.matches(tags=tags, applies_to=applies_to)]

    def list_all(self) -> list[SkillDef]:
        """列出所有已加载的技能。"""
        return list(self._skills.values())

    @property
    def count(self) -> int:
        return len(self._skills)

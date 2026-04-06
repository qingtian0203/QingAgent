from __future__ import annotations

"""
Skill 注册中心 — 管理所有已注册的应用 Skill

Planner 通过注册中心查找能够处理某个意图的 Skill。
"""
from .wechat import WeChatSkill
from .browser import BrowserSkill
from .antigravity import AntigravitySkill
from .qingtian_util import QingTianUtilSkill
from .base import BaseSkill


class SkillRegistry:
    """
    Skill 注册中心。

    用法:
        registry = SkillRegistry()
        registry.auto_register()  # 自动注册所有内置 Skill

        # 查找能处理某个意图的 Skill
        skill = registry.find_skill_for_intent("send_message")
    """

    def __init__(self):
        self._skills: dict[str, BaseSkill] = {}

    def register(self, skill: BaseSkill):
        """注册一个 Skill"""
        self._skills[skill.app_name] = skill
        print(f"📋 已注册 Skill：{skill.app_name} ({len(skill.get_intents())} 个意图)")

    def auto_register(self):
        """自动注册所有内置 Skill"""
        self.register(WeChatSkill())
        self.register(BrowserSkill())
        self.register(AntigravitySkill())
        self.register(QingTianUtilSkill())

    def get_all_skills(self) -> dict[str, BaseSkill]:
        return self._skills

    def get_skill_by_name(self, app_name: str) -> BaseSkill | None:
        """按应用名或别名获取 Skill"""
        # 先精确匹配 app_name
        if app_name in self._skills:
            return self._skills[app_name]
        # 再匹配别名（不区分大小写）
        name_lower = app_name.lower()
        for skill in self._skills.values():
            if name_lower in [a.lower() for a in skill.app_aliases]:
                return skill
        return None

    def find_skill_for_intent(self, intent_name: str) -> tuple[BaseSkill, str] | None:
        """
        查找能处理指定意图的 Skill。

        返回:
            (skill_instance, intent_name) 或 None
        """
        for skill in self._skills.values():
            if intent_name in skill.get_intents():
                return skill, intent_name
        return None

    def get_full_capability_description(self) -> str:
        """
        生成完整的能力描述文档 — 给 Planner AI 看的。

        返回所有 Skill 支持的所有意图和示例。
        """
        lines = ["# QingAgent 能力清单\n"]
        lines.append("以下是所有已注册应用及其支持的操作：\n")

        for name, skill in self._skills.items():
            lines.append(skill.get_intent_descriptions())
            lines.append("---\n")

        return "\n".join(lines)

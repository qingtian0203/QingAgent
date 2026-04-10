from __future__ import annotations

"""
MemoryManager — QingAgent 记忆管理器

负责：
1. 加载 memory.json 中的静态用户信息（联系人、偏好等）
2. 维护最近 N 条对话历史（滑动窗口，不会无限增长）
3. 将记忆内容拼装成可注入 Prompt 的文本

使用方式：
    memory = MemoryManager()
    memory_text = memory.build_context_prompt()  # 注入到 Planner prompt
    memory.append_history("给丸子发条消息", "✅ 已发送")  # 记录一次对话
"""

import json
import os
from collections import deque
from typing import Tuple, Optional

# memory.json 相对于本文件的路径
_DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
_MEMORY_FILE = os.path.join(_DATA_DIR, "memory.json")

# 最多保留的历史条数（滑动窗口）
MAX_HISTORY = 5


class MemoryManager:
    """用户记忆管理器，单例使用。"""

    def __init__(self, max_history: int = MAX_HISTORY):
        self.max_history = max_history
        # 滑动窗口：每条格式为 (user_input, result_message, data_dict)
        # data_dict 保存该轮最后一步的产物（如 screenshot_path、file_path 等）
        self._history: deque[Tuple[str, str, dict]] = deque(maxlen=max_history)
        # 静态记忆（从 memory.json 加载）
        self._static: dict = {}
        self._load_static()

    # ------------------------------------------------------------------ #
    # 静态记忆加载
    # ------------------------------------------------------------------ #

    def _load_static(self):
        """从 memory.json 加载静态记忆，文件不存在时静默忽略。"""
        if not os.path.exists(_MEMORY_FILE):
            print(f"⚠️ [Memory] 未找到记忆文件：{_MEMORY_FILE}，将使用空记忆")
            return
        try:
            with open(_MEMORY_FILE, "r", encoding="utf-8") as f:
                self._static = json.load(f)
            print(f"✅ [Memory] 记忆文件已加载：{_MEMORY_FILE}")
        except Exception as e:
            print(f"❌ [Memory] 记忆文件加载失败：{e}")

    def reload(self):
        """热重载记忆文件（修改 memory.json 后无需重启）。"""
        self._load_static()

    # ------------------------------------------------------------------ #
    # 对话历史管理
    # ------------------------------------------------------------------ #

    def append_history(self, user_input: str, result_message: str, data: Optional[dict] = None):
        """
        记录一条对话到滑动窗口。

        参数:
            user_input: 用户原始指令
            result_message: 执行结果描述（如 "✅ 已发送消息给丸子"）
            data: 可选，该轮最后一步的产物字典（如 {"screenshot_path": "/tmp/abc.png"}）
        """
        self._history.append((user_input, result_message, data or {}))

    def clear_history(self):
        """清空对话历史（不影响静态记忆）。"""
        self._history.clear()

    # ------------------------------------------------------------------ #
    # 快捷方式解析
    # ------------------------------------------------------------------ #

    def resolve_contact_shortcut(self, name: str) -> dict | None:
        """
        查找联系人快捷方式。

        参数:
            name: 口语称呼，如 "丸子"、"群里"

        返回:
            {"app": "WeChat", "target": "丸子", "description": "..."} 或 None
        """
        shortcuts = self._static.get("shortcuts", {}).get("messaging", {})
        return shortcuts.get(name)

    def get_all_shortcuts(self) -> dict:
        """返回所有联系人快捷方式映射。"""
        return self._static.get("shortcuts", {}).get("messaging", {})

    # ------------------------------------------------------------------ #
    # Prompt 构建
    # ------------------------------------------------------------------ #

    def build_context_prompt(self) -> str:
        """
        将静态记忆 + 历史对话拼装成可注入 Prompt 的文本。

        返回示例:
            【用户信息】
            - 姓名：晴天
            - 角色：Android/HarmonyOS Developer
            ...

            【联系人快捷方式】
            - "丸子" → 微信联系人"丸子"
            ...

            【最近对话记录】
            - 用户：给丸子发条消息  →  ✅ 已发送
            ...
        """
        parts = []

        # 1. 用户基本信息
        profile = self._static.get("user_profile", {})
        if profile:
            lines = ["【用户信息】"]
            if profile.get("name"):
                lines.append(f"- 用户姓名：{profile['name']}")
            if profile.get("role"):
                lines.append(f"- 职业身份：{profile['role']}")
            if profile.get("location"):
                lines.append(f"- 所在城市：{profile['location']}")
            parts.append("\n".join(lines))

        # 2. 默认偏好
        prefs = self._static.get("default_preferences", {})
        if prefs:
            lines = ["【默认偏好】"]
            if prefs.get("ide"):
                lines.append(f"- 默认 IDE：{prefs['ide']}")
            if prefs.get("browser"):
                lines.append(f"- 默认浏览器：{prefs['browser']}")
            parts.append("\n".join(lines))

        # 3. 联系人快捷方式
        shortcuts = self.get_all_shortcuts()
        if shortcuts:
            lines = ["【联系人快捷方式（口语称呼→实际微信备注名）】"]
            for alias, info in shortcuts.items():
                lines.append(
                    f'- 用户说"{alias}" → {info["app"]}里的"{info["target"]}"'
                )
            lines.append("- 重要：解析联系人时，必须将口语称呼替换为实际备注名！")
            parts.append("\n".join(lines))

        # 4. 最近对话历史（滑动窗口，含产物路径）
        if self._history:
            lines = [
                f"【最近对话记录（最近 {self.max_history} 条，含产物路径）】",
                "- 如果用户提到'上次的截图'/'前面的图'/'刚才的文件'，请直接使用对应历史条目的产物路径！",
            ]
            history_list = list(self._history)  # 转为列表以获取索引
            for idx, entry in enumerate(history_list):
                # 兼容旧格式（两元组）和新格式（三元组）
                if len(entry) == 3:
                    user_input, result, data = entry
                else:
                    user_input, result = entry
                    data = {}

                # 用从旧到新的编号，最新的是 history1，依此类推
                history_label = f"history{len(history_list) - idx}"
                line = f"- [{history_label}] 用户：{user_input}  →  {result}"
                lines.append(line)

                # 把关键产物路径单独列出，方便 Planner 识别和引用
                if data:
                    artifact_parts = []
                    if data.get("screenshot_path"):
                        artifact_parts.append(f"截图路径={data['screenshot_path']}")
                    if data.get("file_path"):
                        artifact_parts.append(f"文件路径={data['file_path']}")
                    if data.get("value") and isinstance(data["value"], str) and data["value"].startswith("/"):
                        # value 是路径时也展示
                        artifact_parts.append(f"路径={data['value']}")
                    if artifact_parts:
                        lines.append(f"  └─ 产物：{', '.join(artifact_parts)}")

            parts.append("\n".join(lines))

        return "\n\n".join(parts)

from __future__ import annotations

"""
Skill 基类 — 所有应用 Skill 的模板

每个应用的 Skill 需要：
1. 声明自己支持哪些意图（intents）
2. 实现每个意图对应的执行流程
3. 提供应用的基本信息（名称、别名、上下文描述）
"""
from dataclasses import dataclass, field
from qingagent.core import window, vision, actions, verify


@dataclass
class Intent:
    """
    一个意图定义。

    属性:
        name: 意图标识符，如 "send_message"
        description: 自然语言描述，给 AI Planner 看的
        required_slots: 必须提取的参数，如 ["contact_name", "message"]
        optional_slots: 可选参数
        examples: 示例用语，帮助 AI 匹配意图
    """
    name: str
    description: str
    required_slots: list[str] = field(default_factory=list)
    optional_slots: list[str] = field(default_factory=list)
    examples: list[str] = field(default_factory=list)


class BaseSkill:
    """
    应用 Skill 基类 — 所有具体应用 Skill 的父类。

    子类需要实现：
    - app_name: 应用显示名称
    - app_aliases: 进程名别名列表
    - app_context: AI 视觉识别时的上下文描述
    - intents: 支持的意图列表
    - execute_xxx(): 每个意图对应的执行方法
    """

    # --- 子类必须覆写 ---
    app_name: str = "未知应用"
    app_aliases: list[str] = []
    app_context: str = "软件截图"

    def __init__(self):
        self._intents: dict[str, Intent] = {}
        self._window_rect = None
        self._verifier = None
        self.register_intents()

    def register_intents(self):
        """子类在这里注册自己支持的意图"""
        pass

    def add_intent(self, intent: Intent):
        """注册一个意图"""
        self._intents[intent.name] = intent

    def get_intents(self) -> dict[str, Intent]:
        """获取所有支持的意图"""
        return self._intents

    def get_intent_descriptions(self) -> str:
        """生成意图描述文本（给 Planner 用）"""
        lines = [f"# {self.app_name} 支持的操作：\n"]
        for name, intent in self._intents.items():
            lines.append(f"## {name}: {intent.description}")
            if intent.required_slots:
                lines.append(f"   必需参数: {', '.join(intent.required_slots)}")
            if intent.optional_slots:
                lines.append(f"   可选参数: {', '.join(intent.optional_slots)}")
            if intent.examples:
                lines.append(f"   示例: {' / '.join(intent.examples)}")
            lines.append("")
        return "\n".join(lines)

    # --- 通用操作流程 ---

    def activate(self) -> bool:
        """激活应用并获取窗口"""
        import time as _time
        t0 = _time.time()
        result = window.activate_and_find(self.app_aliases)
        if result:
            self._window_rect = result["rect"]
            self._verifier = verify.StepVerifier(
                self._window_rect, context=self.app_context
            )
            print(f"✅ {self.app_name} 窗口就绪：{self._window_rect}")
            print(f"⏱️ [激活应用] 耗时：{_time.time() - t0:.1f}s")
            return True
        else:
            print(f"❌ 无法找到 {self.app_name} 窗口")
            return False

    def screenshot(self, save_path: str = None) -> str | None:
        """截取当前应用窗口"""
        if not self._window_rect:
            print("❌ 尚未定位窗口，请先调用 activate()")
            return None
        return vision.capture_screenshot(self._window_rect, save_path)

    def find_and_click(self, element_desc: str, verify_desc: str = None) -> bool:
        """
        在当前窗口中查找元素并点击 — 最常用的组合操作。

        参数:
            element_desc: 要找的元素描述
            verify_desc: 可选，点击后验证的期望状态

        返回:
            是否成功
        """
        import time as _time

        # 截图
        t0 = _time.time()
        img = self.screenshot()
        if not img:
            return False
        print(f"⏱️ [截图] 耗时：{_time.time() - t0:.1f}s")

        # AI 视觉定位
        t0 = _time.time()
        coords = vision.find_element_with_retry(
            img, element_desc, self.app_context
        )
        print(f"⏱️ [AI视觉定位: {element_desc[:20]}...] 耗时：{_time.time() - t0:.1f}s")
        if not coords:
            return False

        # 点击
        actions.click_at_normalized(self._window_rect, coords)

        # 验证（如果需要）
        if verify_desc and self._verifier:
            t0 = _time.time()
            result = self._verifier.verify(verify_desc)
            print(f"⏱️ [截图验证: {verify_desc[:20]}...] 耗时：{_time.time() - t0:.1f}s")
            return result

        return True

    def read_content(self, question: str) -> str | None:
        """读取当前窗口中的信息"""
        img = self.screenshot()
        if not img:
            return None
        return vision.read_screen_content(img, question, self.app_context)

    def execute(self, intent_name: str, slots: dict) -> dict:
        """
        执行指定意图。

        参数:
            intent_name: 意图名称
            slots: 提取到的参数

        返回:
            {"success": bool, "message": str, "data": any}
        """
        if intent_name not in self._intents:
            return {
                "success": False,
                "message": f"{self.app_name} 不支持操作：{intent_name}",
                "data": None,
            }

        # 调用对应的执行方法：execute_{intent_name}
        method_name = f"execute_{intent_name}"
        method = getattr(self, method_name, None)
        if not method:
            return {
                "success": False,
                "message": f"操作 {intent_name} 尚未实现",
                "data": None,
            }

        try:
            return method(slots)
        except Exception as e:
            return {
                "success": False,
                "message": f"执行 {intent_name} 时出错：{e}",
                "data": None,
            }

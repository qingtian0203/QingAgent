from __future__ import annotations

"""
Antigravity Skill — IDE 代码操控

核心场景：
1. send_prompt - 在 Agent 面板发送指令
2. commit_code - Git 提交代码

输入框定位策略：
- 主路径：macOS 无障碍树命中真实 AXTextArea 输入控件
- 兜底：Cmd+L 打开 Agent 面板后再次 AX 定位
- 最后兜底：AI 视觉识别输入框位置（~15s）
"""
import time as _time
from .base import BaseSkill, Intent
from qingagent.core import actions


class AntigravitySkill(BaseSkill):
    app_name = "Antigravity"
    ui_label = "AI 助手控制"
    app_aliases = ["Antigravity", "AG", "ag", "编辑器", "Cursor"]
    app_context = "IDE 代码编辑器截图"
    cold_start_wait = 5.0   # AG 冷启动需要更长时间加载 Agent 面板

    def register_intents(self):
        self.add_intent(Intent(
            name="send_prompt",
            description="在 Antigravity/AG/Cursor 的 Agent 面板中发送一条消息或代码指令",
            required_slots=["prompt"],
            examples=[
                "给AG发消息说 测试一下",
                "给AG发个消息说 帮我检查代码",
                "让Antigravity帮我检查一下这段代码",
                "给Antigravity发个需求修改登录页面",
                "给编辑器发消息说 重构这个模块",
                "给Cursor发消息说 你好",
            ],
        ))

        self.add_intent(Intent(
            name="commit_code",
            description="通过 Antigravity 提交代码到 Git",
            required_slots=["commit_message"],
            optional_slots=["branch"],
            examples=[
                "提交代码，备注修复了登录 bug",
                "帮我 git commit",
            ],
        ))

    # ============================================================
    #  输入框定位：AX 优先，快捷键只负责兜底唤起 Agent 面板
    # ============================================================

    def _focus_agent_input(self) -> bool:
        """
        聚焦 Agent 面板输入框。

        策略：
        1. 先用 macOS Accessibility 在右侧 Agent 面板底部找真实文本输入控件。
        2. 找不到时，再用 Cmd+1 -> Cmd+L 唤起 / 聚焦 Agent 面板。
        3. 面板唤起后再次使用 AX 定位，避免直接把文本打到错误焦点。
        4. 最后才走 AI 视觉兜底。
        """
        if self._focus_agent_input_by_accessibility():
            return True

        print("⌨️ [快捷键唤起] Cmd+1 (重置焦点) -> Cmd+L (唤起 Agent)")
        t0 = _time.time()
        actions.hotkey("command", "1", delay=0.2)
        actions.hotkey("command", "l", delay=0.8)
        print(f"⏱️ [快捷键唤起] 耗时：{_time.time() - t0:.1f}s")

        return self._focus_agent_input_by_accessibility()

    def _focus_agent_input_by_accessibility(self) -> bool:
        """
        用 macOS Accessibility 命中 Agent 输入框。

        Antigravity 是 IDE 类应用，窗口里可能同时存在代码编辑器、终端、
        搜索框和 Agent 输入框，所以这里优先扫描右侧下半区，减少误点到编辑器。
        """
        if not self._window_rect:
            return False

        x, y, w, h = self._window_rect
        right_pane = (
            x + max(320, w * 0.48),
            y + h * 0.20,
            min(w * 0.52, w - 320),
            h * 0.78,
        )
        print(
            "🧭 [AG无障碍定位] search="
            f"{tuple(round(v) for v in right_pane)}"
        )
        return self.click_text_input_by_accessibility(
            search_rect=right_pane,
            placeholder_keywords=("Ask", "anything", "message", "agent", "输入"),
            label="Antigravity Agent 输入框",
        )

    def _focus_agent_input_by_vision(self) -> bool:
        """
        通过 AI 视觉识别定位 Agent 输入框（慢但准确）。

        作为 AX + 快捷键都失败后的 fallback。
        """
        print("⚠️ 切换 AI 视觉识别模式...")
        t0 = _time.time()
        success = self.find_and_click(
            "界面右侧 Agent 面板中，带有 'Ask anything' 提示的输入框中心"
        )
        print(f"⏱️ [AI视觉定位] 耗时：{_time.time() - t0:.1f}s")
        return success

    # ============================================================
    #  具体意图执行流程
    # ============================================================

    def execute_send_prompt(self, slots: dict) -> dict:
        """
        向 Antigravity Agent 发送指令:
        1. 激活 Antigravity
        2. AX 聚焦输入框（必要时快捷键唤起 Agent 面板，或 AI 视觉兜底）
        3. 输入指令并发送
        """
        prompt = slots["prompt"]

        if not self.activate():
            return {"success": False, "message": "无法激活 Antigravity", "data": None}

        # 定位 Agent 输入框
        if not self._focus_agent_input():
            if not self._focus_agent_input_by_vision():
                return {"success": False, "message": "找不到 Agent 输入框", "data": None}

        actions.type_text(prompt)
        actions.press_key("enter")

        return {
            "success": True,
            "message": f"已发送指令到 Antigravity：{prompt[:50]}...",
            "data": None,
        }

    def execute_commit_code(self, slots: dict) -> dict:
        """
        Git 提交流程:
        1. 激活 Antigravity
        2. 发送 commit 指令给 Agent
        """
        msg = slots["commit_message"]
        prompt = f"请帮我 git add -A && git commit -m \"{msg}\""

        # 复用 send_prompt
        return self.execute_send_prompt({"prompt": prompt})

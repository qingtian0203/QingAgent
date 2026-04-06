from __future__ import annotations

"""
Antigravity Skill — IDE 代码操控

核心场景：
1. send_prompt - 在 Agent 面板发送指令
2. open_file - 打开指定文件
3. commit_code - Git 提交代码
"""
from .base import BaseSkill, Intent
from qingagent.core import actions


class AntigravitySkill(BaseSkill):
    app_name = "Antigravity"
    app_aliases = ["Antigravity"]
    app_context = "IDE 代码编辑器截图"

    def register_intents(self):
        self.add_intent(Intent(
            name="send_prompt",
            description="在 Antigravity 的 Agent 面板中发送一条代码指令/需求",
            required_slots=["prompt"],
            examples=[
                "让 Antigravity 帮我检查一下这段代码",
                "给 Antigravity 发个需求修改登录页面",
                "用 Antigravity 重构这个模块",
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

    # --- 具体执行流程 ---

    def execute_send_prompt(self, slots: dict) -> dict:
        """
        向 Antigravity Agent 发送指令:
        1. 激活 Antigravity
        2. 找到 Agent 输入框
        3. 输入指令并发送
        """
        prompt = slots["prompt"]

        if not self.activate():
            return {"success": False, "message": "无法激活 Antigravity", "data": None}

        # 定位 Agent 输入框
        success = self.find_and_click(
            "界面右侧 Agent 面板中，带有 'Ask anything' 提示的输入框中心"
        )
        if not success:
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

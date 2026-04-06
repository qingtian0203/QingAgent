from __future__ import annotations

"""
微信 Skill — 消息查看、消息提取、消息发送

专注于晴帅最常用的三个核心功能：
1. check_messages - 查看某个聊天/群的最新消息
2. send_message - 给指定联系人/群发消息
3. extract_messages - 提取聊天记录内容（返回文本）
"""
from .base import BaseSkill, Intent
from qingagent.core import vision, actions


class WeChatSkill(BaseSkill):
    app_name = "微信"
    app_aliases = ["WeChat", "wechat", "微信"]
    app_context = "微信聊天界面截图"

    def register_intents(self):
        self.add_intent(Intent(
            name="send_message",
            description="给指定联系人或群发送一条消息",
            required_slots=["contact_name", "message"],
            examples=[
                "给晴天发条微信说下午开会",
                "在工作群发一下会议纪要",
                "微信告诉老板已经完成了",
            ],
        ))

        self.add_intent(Intent(
            name="check_messages",
            description="查看某个联系人或群的最新消息",
            required_slots=["contact_name"],
            optional_slots=["count"],
            examples=[
                "看看工作群有没有新消息",
                "微信上晴天给我发了什么",
                "查一下产品群最后聊了啥",
            ],
        ))

        self.add_intent(Intent(
            name="extract_messages",
            description="提取并返回聊天记录的文字内容",
            required_slots=["contact_name"],
            optional_slots=["count", "keyword"],
            examples=[
                "把工作群最近的消息整理一下",
                "提取和老板的聊天记录",
            ],
        ))

    # --- 具体执行流程 ---

    def execute_send_message(self, slots: dict) -> dict:
        """
        发消息流程:
        1. 激活微信
        2. 在联系人列表找到目标并点击
        3. 定位输入框并点击
        4. 输入消息并发送
        """
        contact = slots["contact_name"]
        message = slots["message"]

        # 步骤 1：激活微信
        if not self.activate():
            return {"success": False, "message": "无法打开微信", "data": None}

        # 步骤 2：找到联系人并点击（不需要验证，直接继续）
        success = self.find_and_click(
            f"左侧聊天列表中名字包含'{contact}'的那一行的中心",
        )
        if not success:
            return {"success": False, "message": f"找不到联系人：{contact}", "data": None}

        # 等聊天窗口完全打开
        import time as _time
        _time.sleep(1.0)

        # 步骤 3：直接点击输入框（位置固定，不需要 AI 定位）
        # 根据 AI 历史定位数据推算：输入框中心在 rx≈650, ry≈850
        t0 = _time.time()
        actions.click_at_normalized(self._window_rect, {"rx": 650, "ry": 850})
        print(f"⏱️ [输入框直接定位] 耗时：{_time.time() - t0:.1f}s")

        # 步骤 4：输入并发送
        actions.type_text(message)
        actions.press_key("enter")

        return {
            "success": True,
            "message": f"已给 {contact} 发送消息：{message}",
            "data": None,
        }

    def execute_check_messages(self, slots: dict) -> dict:
        """
        查看消息流程:
        1. 激活微信
        2. 切到目标聊天
        3. 截图阅读最新消息
        """
        contact = slots["contact_name"]
        count = slots.get("count", 5)

        if not self.activate():
            return {"success": False, "message": "无法打开微信", "data": None}

        # 找到联系人
        success = self.find_and_click(
            f"左侧聊天列表中名字包含'{contact}'的那一行的中心",
        )
        if not success:
            return {"success": False, "message": f"找不到：{contact}", "data": None}

        # 读取消息内容
        content = self.read_content(
            f"请阅读聊天窗口中最近的 {count} 条消息，按时间顺序列出"
            f"每条消息的发送者和内容。"
        )

        return {
            "success": True,
            "message": f"{contact} 的最新消息",
            "data": content,
        }

    def execute_extract_messages(self, slots: dict) -> dict:
        """提取消息 — 类似 check_messages 但专注于结构化输出"""
        contact = slots["contact_name"]

        if not self.activate():
            return {"success": False, "message": "无法打开微信", "data": None}

        success = self.find_and_click(
            f"左侧聊天列表中名字包含'{contact}'的那一行的中心",
        )
        if not success:
            return {"success": False, "message": f"找不到：{contact}", "data": None}

        content = self.read_content(
            f"请提取当前聊天窗口中所有可见的消息。"
            f"格式：[发送者] 消息内容"
            f"每条消息一行。"
        )

        return {
            "success": True,
            "message": f"已提取 {contact} 的聊天记录",
            "data": content,
        }

from __future__ import annotations

"""
微信 Skill — 消息查看、消息提取、消息发送

专注于晴帅最常用的三个核心功能：
1. check_messages - 查看某个聊天/群的最新消息
2. send_message - 给指定联系人/群发消息
3. extract_messages - 提取聊天记录内容（返回文本）

联系人定位策略：
- 主路径：搜索框搜索（~2s，不依赖 AI）
- 兜底：AI 视觉识别（~20s，万一搜索失败时使用）
"""
import time as _time
from .base import BaseSkill, Intent
from qingagent.core import vision, actions


# ============================================================
#  微信界面固定坐标（归一化 0-1000）
#  基于实际测试数据，微信窗口布局稳定
# ============================================================
# 搜索框位置（左上角 "🔍 搜索"）
SEARCH_BOX = {"rx": 140, "ry": 45}
# 搜索结果第一条（搜索框正下方）
SEARCH_FIRST_RESULT = {"rx": 140, "ry": 160}
# 聊天输入框（右侧底部）
CHAT_INPUT_BOX = {"rx": 650, "ry": 850}


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

    # ============================================================
    #  联系人定位：搜索优先，AI 视觉兜底
    # ============================================================

    def _find_contact(self, contact: str) -> bool:
        """
        定位并打开指定联系人的聊天窗口。

        策略：
        1. 先用搜索框搜索（快，~2s）
        2. 如果搜索失败，退回 AI 视觉识别（慢，~20s）

        返回:
            True = 成功打开聊天窗口
        """
        # 主路径：搜索框
        print(f"🔍 [搜索模式] 正在搜索联系人：{contact}")
        t0 = _time.time()
        success = self._find_contact_by_search(contact)
        print(f"⏱️ [搜索定位] 耗时：{_time.time() - t0:.1f}s")

        if success:
            return True

        # 兜底：AI 视觉识别
        print(f"⚠️ 搜索模式未命中，切换 AI 视觉识别...")
        t0 = _time.time()
        success = self._find_contact_by_vision(contact)
        print(f"⏱️ [AI视觉定位] 耗时：{_time.time() - t0:.1f}s")

        return success

    def _find_contact_by_search(self, contact: str) -> bool:
        """
        通过搜索框定位联系人（无 AI 调用，纯坐标操作）。

        流程：
        1. 点击搜索框
        2. 输入联系人名字
        3. 等待搜索结果
        4. 点击第一个结果
        5. 按 Esc 退出搜索状态
        """
        rect = self._window_rect

        # 1. 点击搜索框
        actions.click_at_normalized(rect, SEARCH_BOX, delay=0.5)

        # 2. 先清空搜索框已有内容，再输入联系人名
        actions.hotkey("command", "a", delay=0.1)
        actions.type_text(contact)

        # 3. 等搜索结果加载
        _time.sleep(1.2)

        # 4. 点击第一个搜索结果
        actions.click_at_normalized(rect, SEARCH_FIRST_RESULT, delay=0.8)

        # 5. 按 Esc 退出搜索状态（回到正常聊天界面）
        actions.press_key("escape", delay=0.3)

        return True

    def _find_contact_by_vision(self, contact: str) -> bool:
        """
        通过 AI 视觉识别定位联系人（慢但准确）。

        作为搜索模式的 fallback 使用。
        """
        return self.find_and_click(
            f"左侧聊天列表中名字包含'{contact}'的那一行的中心",
        )

    # ============================================================
    #  具体意图执行流程
    # ============================================================

    def execute_send_message(self, slots: dict) -> dict:
        """
        发消息流程:
        1. 激活微信
        2. 搜索并切到联系人（搜索优先 / AI兜底）
        3. 点击输入框
        4. 输入消息并发送
        """
        contact = slots["contact_name"]
        message = slots["message"]

        # 步骤 1：激活微信
        if not self.activate():
            return {"success": False, "message": "无法打开微信", "data": None}

        # 步骤 2：定位联系人
        if not self._find_contact(contact):
            return {"success": False, "message": f"找不到联系人：{contact}", "data": None}

        # 等聊天窗口完全打开
        _time.sleep(0.8)

        # 步骤 3：点击输入框（位置固定）
        t0 = _time.time()
        actions.click_at_normalized(self._window_rect, CHAT_INPUT_BOX)
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

        if not self._find_contact(contact):
            return {"success": False, "message": f"找不到：{contact}", "data": None}

        _time.sleep(0.5)

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

        if not self._find_contact(contact):
            return {"success": False, "message": f"找不到：{contact}", "data": None}

        _time.sleep(0.5)

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


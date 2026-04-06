from __future__ import annotations

"""
浏览器 Skill — 打开网页、页面操作、JS 交互

核心场景：
1. open_url - 打开指定网址
2. find_element_on_page - 在页面中定位元素（搜索框、按钮等）
3. read_page_content - 阅读页面内容
4. js_interact - 在 JS 交互页面定位和操作元素
"""
import os
from .base import BaseSkill, Intent
from qingagent.core import actions


class BrowserSkill(BaseSkill):
    app_name = "浏览器"
    app_aliases = ["Google Chrome", "Chrome", "Safari", "Arc"]
    app_context = "网页浏览器截图"

    def register_intents(self):
        self.add_intent(Intent(
            name="open_url",
            description="在浏览器中打开指定网址",
            required_slots=["url"],
            examples=[
                "打开百度",
                "帮我打开需求文档的网页",
                "浏览器访问 localhost:8080",
            ],
        ))

        self.add_intent(Intent(
            name="find_and_click_element",
            description="在当前网页中找到指定元素并点击",
            required_slots=["element_description"],
            examples=[
                "点击页面上的登录按钮",
                "找到搜索框并点击",
                "点击导航栏的'项目管理'",
            ],
        ))

        self.add_intent(Intent(
            name="read_page_content",
            description="阅读当前网页上的内容并提取信息",
            required_slots=["question"],
            examples=[
                "这个需求文档页面说了什么",
                "看看页面上有哪些待办事项",
                "读一下表格里的数据",
            ],
        ))

        self.add_intent(Intent(
            name="fill_form",
            description="在网页表单中填写内容",
            required_slots=["field_description", "value"],
            examples=[
                "在搜索框里输入关键字",
                "把用户名填上",
            ],
        ))

    # --- 具体执行流程 ---

    def execute_open_url(self, slots: dict) -> dict:
        """通过 AppleScript 或 shell 打开 URL"""
        url = slots["url"]
        # 确保有协议前缀
        if not url.startswith(("http://", "https://")):
            url = f"https://{url}"

        os.system(f'open "{url}"')

        import time
        time.sleep(2)

        if not self.activate():
            return {"success": False, "message": "浏览器未响应", "data": None}

        return {
            "success": True,
            "message": f"已打开：{url}",
            "data": None,
        }

    def execute_find_and_click_element(self, slots: dict) -> dict:
        """在当前页面中定位并点击元素"""
        desc = slots["element_description"]

        if not self.activate():
            return {"success": False, "message": "浏览器未响应", "data": None}

        success = self.find_and_click(desc)
        return {
            "success": success,
            "message": f"{'已点击' if success else '未找到'}：{desc}",
            "data": None,
        }

    def execute_read_page_content(self, slots: dict) -> dict:
        """阅读页面内容"""
        question = slots["question"]

        if not self.activate():
            return {"success": False, "message": "浏览器未响应", "data": None}

        content = self.read_content(question)
        return {
            "success": content is not None,
            "message": "页面内容读取完成" if content else "读取失败",
            "data": content,
        }

    def execute_fill_form(self, slots: dict) -> dict:
        """定位表单字段并填写"""
        field_desc = slots["field_description"]
        value = slots["value"]

        if not self.activate():
            return {"success": False, "message": "浏览器未响应", "data": None}

        success = self.find_and_click(field_desc)
        if not success:
            return {"success": False, "message": f"找不到：{field_desc}", "data": None}

        actions.type_text(value)
        return {
            "success": True,
            "message": f"已在 {field_desc} 中输入内容",
            "data": None,
        }

from __future__ import annotations

"""
晴天 Util Skill — 桌面工具集操控

核心场景：
1. click_feature - 点击晴天 Util 中的指定功能按钮
2. run_api_test - 使用 API 调试器测试接口
3. check_calendar - 查看日历任务
4. manage_meeting - 会议录音相关操作
"""
from .base import BaseSkill, Intent
from qingagent.core import actions


class QingTianUtilSkill(BaseSkill):
    app_name = "晴天Util"
    app_aliases = ["晴天", "QingTian", "qingtian"]
    app_context = "晴天Util桌面工具截图"

    def register_intents(self):
        self.add_intent(Intent(
            name="click_feature",
            description="点击晴天 Util 中的指定功能模块",
            required_slots=["feature_name"],
            examples=[
                "打开晴天的日历功能",
                "用晴天的 API 调试器",
                "晴天里打开会议录音",
            ],
        ))

        self.add_intent(Intent(
            name="run_api_test",
            description="使用晴天 Util 的 API 调试器发送请求",
            required_slots=["api_url"],
            optional_slots=["method", "params", "headers"],
            examples=[
                "用晴天调试一下这个接口",
                "帮我测试这个 API",
            ],
        ))

        self.add_intent(Intent(
            name="check_calendar",
            description="查看晴天日历中的任务和日程",
            optional_slots=["date"],
            examples=[
                "看看今天有什么任务",
                "晴天日历今天的安排",
                "查一下这周的待办",
            ],
        ))

        self.add_intent(Intent(
            name="pull_and_restart",
            description="拉取最新代码并重启QingAgent服务",
            examples=[
                "拉取更新并重启",
                "更新QingAgent",
                "打开晴天Util拉取更新并重启",
            ],
        ))

    # --- 具体执行流程 ---

    def execute_click_feature(self, slots: dict) -> dict:
        """点击指定功能模块"""
        feature = slots["feature_name"]

        if not self.activate():
            return {"success": False, "message": "无法打开晴天Util", "data": None}

        # 先看看顶部导航栏或功能列表
        success = self.find_and_click(
            f"界面中标签或按钮为'{feature}'的功能入口",
            verify_desc=f"{feature} 功能界面已打开"
        )

        return {
            "success": success,
            "message": f"{'已打开' if success else '未找到'} {feature}",
            "data": None,
        }

    def execute_run_api_test(self, slots: dict) -> dict:
        """使用 API 调试器"""
        url = slots["api_url"]

        if not self.activate():
            return {"success": False, "message": "无法打开晴天Util", "data": None}

        # 先切到 API 调试器
        self.find_and_click("API调试器 或 API Tester 的标签/按钮")

        # 找到 URL 输入框
        success = self.find_and_click("URL 输入框或地址栏")
        if not success:
            return {"success": False, "message": "找不到 URL 输入框", "data": None}

        actions.type_text(url)

        # 点击发送
        self.find_and_click("发送按钮 或 Send 按钮")

        # 等待结果并读取
        import time
        time.sleep(2)
        result = self.read_content("请读取 API 响应的内容")

        return {
            "success": True,
            "message": f"API 测试完成：{url}",
            "data": result,
        }

    def execute_check_calendar(self, slots: dict) -> dict:
        """查看日历任务"""
        date = slots.get("date", "今天")

        if not self.activate():
            return {"success": False, "message": "无法打开晴天Util", "data": None}

        # 切到日历
        self.find_and_click("日历 或 Calendar 的标签/按钮")

        import time
        time.sleep(1)

        content = self.read_content(
            f"请阅读日历中{date}的所有任务和日程安排，列出每项的标题和状态。"
        )

        return {
            "success": True,
            "message": f"{date}的日程",
            "data": content,
        }

    def execute_pull_and_restart(self, slots: dict) -> dict:
        """
        拉取更新并重启流程：
        1. 激活晴天Util
        2. 点击 AI Agent 标签
        3. 点击 拉取更新并重启 按钮
        """
        import time as _time

        if not self.activate():
            return {"success": False, "message": "无法打开晴天Util", "data": None}

        # 步骤 1：点击"AI Agent"标签页
        self.check_cancel()
        step1 = self.find_and_click(
            "顶部导航栏中标题为'AI Agent'的标签按钮",
        )
        if not step1:
            return {"success": False, "message": "找不到 AI Agent 标签", "data": None}

        _time.sleep(1.0)

        # 步骤 2：点击"拉取更新并重启"按钮
        self.check_cancel()
        step2 = self.find_and_click(
            "蓝色的'拉取更新并重启'按钮（或包含'拉取更新'字样的按钮）",
        )

        return {
            "success": step2,
            "message": "已点击拉取更新并重启" if step2 else "找不到拉取更新按钮",
            "data": None,
        }

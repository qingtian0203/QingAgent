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
            name="add_calendar",
            description="在晴天日历中添加新的任务或日程",
            required_slots=["title"],
            optional_slots=["date", "time", "description"],
            examples=[
                "添加明天的工作日历：开周会",
                "在日历里加一个任务",
                "帮我添加一个日程安排",
                "日历新建：下午3点产品评审",
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

    def execute_add_calendar(self, slots: dict) -> dict:
        """
        通过 AI 视觉操控晴天Util添加日历任务。
        弹窗布局（自上而下）：
        1. 标题"新建任务"
        2. "任务内容"文本框（白色大输入区域）
        3. "任务类型"四个按钮：⚡临时任务 | 🔗接口 | 🧪提测 | 🚀上线
        4. "所属项目"四个按钮：OA | C端 | B端 | 其他
        5. "日期"年/月/日下拉 + 快捷按钮：今天 | 明天 | 后天 | 下周
        6. 底部：取消 | ✓ 确认添加（绿色按钮）
        """
        import time as _time

        title = slots["title"]
        date_raw = slots.get("date", "今天")
        task_type = slots.get("type", "")
        project = slots.get("project", "")

        if not self.activate():
            return {"success": False, "message": "无法打开晴天Util", "data": None}

        # 步骤 1：切到工作日历标签
        self.check_cancel()
        self.find_and_click("顶部标签栏中'工作日历'文字")
        _time.sleep(1)

        # 步骤 2：点击 "+ 添加" 按钮（绿色小按钮，在右侧任务面板的右上角）
        self.check_cancel()
        add_ok = self.find_and_click("右侧任务面板右上角的绿色'+ 添加'按钮")
        if not add_ok:
            return {"success": False, "message": "找不到添加按钮", "data": None}
        _time.sleep(1)

        # 弹窗出现后，需要重新截图（弹窗是独立窗口，可能在最前面）
        # 步骤 3：点击"任务内容"下方的白色文本输入区域
        self.check_cancel()
        content_ok = self.find_and_click(
            "弹窗中'任务内容'标签下方的白色文本输入框区域（大的空白方框）"
        )
        if content_ok:
            _time.sleep(0.3)
            actions.type_text(title)
            _time.sleep(0.3)

        # 步骤 4：选择任务类型（如果指定）
        if task_type:
            self.check_cancel()
            type_map = {
                "临时": "⚡临时任务", "接口": "🔗接口",
                "提测": "🧪提测", "上线": "🚀上线",
            }
            type_text = type_map.get(task_type, task_type)
            self.find_and_click(
                f"弹窗中'任务类型'行的'{type_text}'按钮"
            )
            _time.sleep(0.3)

        # 步骤 5：选择项目（如果指定）
        if project:
            self.check_cancel()
            self.find_and_click(
                f"弹窗中'所属项目'行的'{project}'按钮"
            )
            _time.sleep(0.3)

        # 步骤 6：选择日期
        self.check_cancel()
        quick_dates = ["今天", "明天", "后天", "下周"]
        if date_raw in quick_dates:
            # 快捷日期：直接点快捷按钮
            self.find_and_click(
                f"弹窗中日期区域下方的'{date_raw}'快捷按钮"
            )
            _time.sleep(0.3)
        elif date_raw:
            # 具体日期：解析后通过下拉菜单选择
            from datetime import datetime
            year, month, day = None, None, None
            try:
                # 尝试 YYYY-MM-DD 格式
                parsed = datetime.strptime(date_raw, "%Y-%m-%d")
                year, month, day = parsed.year, parsed.month, parsed.day
            except ValueError:
                try:
                    # 尝试 M月D日 格式
                    now = datetime.now()
                    parsed = datetime.strptime(f"{now.year}年{date_raw}", "%Y年%m月%d日")
                    year, month, day = parsed.year, parsed.month, parsed.day
                except ValueError:
                    # 让 AI 自己理解日期文字的含义
                    pass

            if year and month and day:
                # 选择月份：点击"月"右边的下拉箭头，再从列表中点月数字
                self.check_cancel()
                self.find_and_click(
                    "弹窗日期行中'月'字右边的下拉选择器按钮（显示当前月份数字的灰色下拉框）"
                )
                _time.sleep(0.5)
                self.find_and_click(
                    f"弹出的下拉列表中数字'{month}'选项"
                )
                _time.sleep(0.3)

                # 选择日：点击"日"右边的下拉箭头，再从列表中点日数字
                self.check_cancel()
                self.find_and_click(
                    "弹窗日期行中'日'字右边的下拉选择器按钮（显示当前日期数字的灰色下拉框）"
                )
                _time.sleep(0.5)
                self.find_and_click(
                    f"弹出的下拉列表中数字'{day}'选项"
                )
                _time.sleep(0.3)

        # 步骤 7：点击绿色的"✓ 确认添加"按钮
        self.check_cancel()
        _time.sleep(0.5)
        save_ok = self.find_and_click(
            "弹窗底部右侧的绿色'确认添加'按钮"
        )

        return {
            "success": save_ok,
            "message": f"{'已添加' if save_ok else '添加失败'}日程：{title}",
            "data": {"title": title, "date": date_raw, "type": task_type},
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

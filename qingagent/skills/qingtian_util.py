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
        """查看日历任务（纯数据库直连，无需打开 UI）"""
        date_raw = slots.get("date", "今天")
        
        import os, json, re
        from datetime import datetime, timedelta
        
        # 1. 简易 NLP 日期推导
        text = date_raw.strip().lower()
        now = datetime.now()
        target_date_str = now.strftime("%Y-%m-%d")
        
        if text in ["今天", "今日", "today"]:
            target_date_str = now.strftime("%Y-%m-%d")
        elif text in ["明天", "明日", "tomorrow"]:
            target_date_str = (now + timedelta(days=1)).strftime("%Y-%m-%d")
        elif text in ["昨天", "昨日", "yesterday"]:
            target_date_str = (now - timedelta(days=1)).strftime("%Y-%m-%d")
        elif text in ["后天"]:
            target_date_str = (now + timedelta(days=2)).strftime("%Y-%m-%d")
        else:
            match = re.search(r"(\d+)月(\d+)日", text)
            if match:
                try:
                    target_date_str = datetime(now.year, int(match.group(1)), int(match.group(2))).strftime("%Y-%m-%d")
                except: pass

        print(f"📅 [直连数据库] 查询日期：{date_raw} → {target_date_str}")

        # 2. 直读本地持久化数据库，不打开任何 UI
        db_path = os.path.expanduser("~/AIProject/QingUtil/data/calendar_data.json")
        tasks = []
        if os.path.exists(db_path):
            try:
                with open(db_path, "r", encoding="utf-8") as f:
                    db_data = json.load(f)
                
                for t in db_data.get("tasks", []):
                    if t.get("date") == target_date_str:
                        project_label = t.get("project", "")
                        type_label = t.get("type", "")
                        task_type_str = f"{project_label} · {type_label}".strip(" ·")
                        tasks.append({
                            "title": t.get("content", ""),
                            "task_type": task_type_str,
                            "completed": bool(t.get("done", False))
                        })
                print(f"✅ [直连数据库] 命中 {len(tasks)} 条任务")
            except Exception as e:
                print(f"❌ 直连获取日历数据源失败: {e}")
                return {"success": False, "message": f"读取数据库失败: {e}", "data": None}
        else:
            print(f"⚠️ 数据库文件不存在: {db_path}")

        no_task_msg = "当日暂无任务安排" if not tasks else f"共 {len(tasks)} 条任务"
        return {
            "success": True,
            "message": f"{date_raw}的日程查询完毕（{no_task_msg}）",
            "data": {
                "ui_type": "calendar_query",
                "date": date_raw,
                "target_date": target_date_str,
                "tasks": tasks
            }
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

        优化：快捷日期场景（今天/明天/后天/下周）只截一次图，
        批量获取输入框+日期按钮+确认按钮坐标，减少2/3的AI推理次数。
        """
        import time as _time
        from qingagent.core import actions
        from qingagent.core import vision

        title = slots["title"]
        date_raw = slots.get("date", "今天")
        task_type = slots.get("type", "")
        project = slots.get("project", "")
        quick_dates = ["今天", "明天", "后天", "下周"]
        is_quick_date = date_raw in quick_dates

        if not self.activate():
            return {"success": False, "message": "无法打开晴天Util", "data": None}

        # 步骤 1：切到工作日历标签
        # ⚠️ 先截一次热身图，确保 _last_screenshot_rect 已被赋值含 PAD 的扩边 rect
        # 否则激活后第一次 find_and_click 会直接用无 PAD 的 _window_rect 做坐标换算导致点歪
        self.screenshot()
        self.check_cancel()
        self.find_and_click("顶部标签栏中'工作日历'文字")
        _time.sleep(1)

        # 步骤 2：点击 "+ 添加" 按钮
        # ⚠️ 注意：窗口右上角还有一个紫色"一键升级"大按钮，绝对不能点那个！
        # 目标是日历右侧任务列表头部"4月XX日 周X"标题行最右边的绿色小"+ 添加"按钮
        self.check_cancel()
        add_ok = self.find_and_click(
            "日历右侧任务列表区域顶部、日期标题行（如'4月14日 周二'）最右侧的绿色小'+ 添加'按钮，注意不要点窗口顶部的紫色'一键升级'按钮"
        )
        if not add_ok:
            return {"success": False, "message": "找不到添加按钮", "data": None}
        _time.sleep(1)

        # 🔀 切换到弹窗截图区域
        self.switch_to_popup()
        _time.sleep(0.3)

        # ─────────────────────────────────────────────────────────────
        # 快捷日期场景：一次截图批量定位输入框 + 日期按钮 + 确认按钮
        # ─────────────────────────────────────────────────────────────
        if is_quick_date:
            self.check_cancel()
            type_map = {"临时": "⚡临时任务", "接口": "🔗接口", "提测": "🧪提测", "上线": "🚀上线"}
            type_text = type_map.get(task_type, task_type) if task_type else ""

            elements = {
                "input":    "标题'任务内容'正下方的极其宽大的纯白色、空白圆角矩形区域的绝对正中心处（这是输入框内部）",
                "date_btn": f"日期区域下方快捷按钮中的'{date_raw}'按钮",
                "confirm":  "底部右侧的绿色'✓ 确认添加'按钮",
            }
            if task_type and type_text:
                elements["type_btn"] = f"'任务类型'行中的'{type_text}'按钮"
            if project:
                elements["project_btn"] = f"'所属项目'行中的'{project}'按钮"

            print(f"📸 批量定位弹窗元素（共 {len(elements)} 个）...")
            img = self.screenshot()
            coords = vision.find_elements_batch(img, elements, context="晴天Util新建任务弹窗") if img else None

            def _fallback():
                """批量定位失败时的逐步回退操作"""
                self.find_and_click("标题'任务内容'正下方的巨大纯白色空白矩形区域的内部正中心")
                _time.sleep(0.3)
                actions.type_text(title)
                _time.sleep(0.2)
                if task_type and type_text:
                    self.find_and_click(f"'任务类型'行中的'{type_text}'按钮")
                    _time.sleep(0.2)
                if project:
                    self.find_and_click(f"'所属项目'行中的'{project}'按钮")
                    _time.sleep(0.2)
                self.find_and_click(f"'日期'区域下方的'{date_raw}'按钮")
                _time.sleep(0.2)
                return self.find_and_click("底部右侧的绿色'✓ 确认添加'按钮")

            if not coords:
                print("⚠️ 批量定位失败，回退到逐步定位")
                save_ok = _fallback()
            else:
                def _click_key(key):
                    c = coords.get(key)
                    if not c:
                        return False
                    # 获取最新的一张截图由于弹窗扩屏产生的真实矩形框范围！
                    target_rect = getattr(self, '_last_screenshot_rect', self._window_rect)
                    actions.click_at_normalized(target_rect, c)
                    return True

                # ① 输入框 → 输入文字
                _click_key("input")
                _time.sleep(0.3)
                actions.type_text(title)
                _time.sleep(0.2)
                # ② 可选：任务类型
                if task_type and "type_btn" in coords:
                    _click_key("type_btn")
                    _time.sleep(0.2)
                # ③ 可选：所属项目
                if project and "project_btn" in coords:
                    _click_key("project_btn")
                    _time.sleep(0.2)
                # ④ 快捷日期
                _click_key("date_btn")
                _time.sleep(0.2)
                # ⑤ 确认添加
                save_ok = _click_key("confirm")

        else:
            # ─────────────────────────────────────────────────────────────
            # 具体日期场景：分步操作（下拉框改变界面，必须逐步截图）
            # ─────────────────────────────────────────────────────────────
            from datetime import datetime

            # 输入任务内容
            self.check_cancel()
            content_ok = self.find_and_click("标题'任务内容'正下方的巨大纯白色空白矩形区域的内部正中心")
            if content_ok:
                _time.sleep(0.3)
                actions.type_text(title)
                _time.sleep(0.2)

            # 可选：任务类型
            if task_type:
                self.check_cancel()
                type_map = {"临时": "⚡临时任务", "接口": "🔗接口", "提测": "🧪提测", "上线": "🚀上线"}
                type_text = type_map.get(task_type, task_type)
                self.find_and_click(f"'任务类型'行中的'{type_text}'按钮")
                _time.sleep(0.2)

            # 可选：所属项目
            if project:
                self.check_cancel()
                self.find_and_click(f"'所属项目'行中的'{project}'按钮")
                _time.sleep(0.2)

            # 解析具体日期
            year, month, day = None, None, None
            try:
                parsed = datetime.strptime(date_raw, "%Y-%m-%d")
                year, month, day = parsed.year, parsed.month, parsed.day
            except ValueError:
                try:
                    now = datetime.now()
                    parsed = datetime.strptime(f"{now.year}年{date_raw}", "%Y年%m月%d日")
                    year, month, day = parsed.year, parsed.month, parsed.day
                except ValueError:
                    pass

            if year and month and day:
                # 选月份
                self.check_cancel()
                self.find_and_click("'日期'行中'月'字右边的下拉选择器（显示月份数字的灰色框）")
                _time.sleep(0.5)
                self.find_and_click(f"弹出的下拉列表中数字'{month}'选项")
                _time.sleep(0.3)
                # 选日期
                self.check_cancel()
                self.find_and_click("'日期'行中'日'字右边的下拉选择器（显示日期数字的灰色框）")
                _time.sleep(0.5)
                self.find_and_click(f"弹出的下拉列表中数字'{day}'选项")
                _time.sleep(0.3)

            # 确认添加
            self.check_cancel()
            _time.sleep(0.3)
            save_ok = self.find_and_click("底部右侧的绿色'✓ 确认添加'按钮")

        # 🔀 恢复到主窗口
        self.switch_to_main()

        return {
            "success": save_ok,
            "message": f"{'已添加' if save_ok else '添加失败'}日程",
            "data": {
                "ui_type": "calendar_task", 
                "title": title, 
                "date": date_raw, 
                "task_type": task_type
            },
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

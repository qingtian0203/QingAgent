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

        self.add_intent(Intent(
            name="play_24point",
            description="自动玩24点游戏：读取页面上的4个数字并计算出答案",
            optional_slots=["rounds"],
            examples=[
                "帮我玩24点",
                "打开24点游戏帮我玩",
                "play 24 point",
                "自动玩24点",
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

    # --- 24点求解器（穷举法，保证100%正确） ---
    @staticmethod
    def _solve_24(numbers: list[int]) -> str | None:
        """穷举所有可能的运算组合，找到等于24的表达式"""
        from itertools import permutations, product
        ops = ['+', '-', '*', '/']
        # 五种括号模板
        templates = [
            '(({a}{o1}{b}){o2}{c}){o3}{d}',
            '({a}{o1}({b}{o2}{c})){o3}{d}',
            '({a}{o1}{b}){o2}({c}{o3}{d})',
            '{a}{o1}(({b}{o2}{c}){o3}{d})',
            '{a}{o1}({b}{o2}({c}{o3}{d}))',
        ]
        for perm in permutations(numbers):
            for op_combo in product(ops, repeat=3):
                for tmpl in templates:
                    expr = tmpl.format(
                        a=perm[0], b=perm[1], c=perm[2], d=perm[3],
                        o1=op_combo[0], o2=op_combo[1], o3=op_combo[2]
                    )
                    try:
                        if abs(eval(expr) - 24) < 0.001:
                            return expr
                    except (ZeroDivisionError, SyntaxError):
                        continue
        return None

    def execute_play_24point(self, slots: dict) -> dict:
        """
        自动玩24点游戏：
        1. 截图读取页面上的4个数字
        2. 穷举算出答案
        3. 点击输入框填入答案
        4. 点击提交按钮
        """
        import time as _time
        import re

        rounds = int(slots.get('rounds', 1))
        results = []

        for r in range(rounds):
            self.check_cancel()
            if r > 0:
                print(f"\n--- 第 {r+1} 轮 ---")

            if not self.activate():
                return {"success": False, "message": "浏览器未响应", "data": None}

            # 步骤 1：截图读取数字
            print("👁 正在读取页面上的4个数字...")
            content = self.read_content(
                "请读取页面中展示的4个数字卡片上的数字，只返回4个数字，用逗号分隔。例如: 3,8,7,2"
            )
            if not content:
                return {"success": False, "message": "无法读取页面内容", "data": None}

            # 提取数字
            nums = re.findall(r'\d+', content)
            if len(nums) < 4:
                return {"success": False, "message": f"读取到的数字不足：{content}", "data": None}
            numbers = [int(n) for n in nums[:4]]
            print(f"🎴 读取到4个数字：{numbers}")

            # 步骤 2：穷举求解
            self.check_cancel()
            print("🧠 正在计算答案...")
            t0 = _time.time()
            solution = self._solve_24(numbers)
            print(f"⏱️ [求解] 耗时：{_time.time()-t0:.2f}s")

            if not solution:
                results.append(f"轮{r+1}: {numbers} → 无解")
                print(f"❌ 无解：{numbers}")
                if r < rounds - 1:
                    self.find_and_click("下一题按钮")
                    _time.sleep(1)
                continue

            print(f"✅ 找到答案：{solution} = 24")

            # 步骤 3：点击输入框并填入答案
            self.check_cancel()
            click_ok = self.find_and_click("输入框或答案输入区域")
            if not click_ok:
                return {"success": False, "message": "找不到输入框", "data": None}

            _time.sleep(0.3)
            actions.type_text(solution)
            _time.sleep(0.3)

            # 步骤 4：点击提交
            self.check_cancel()
            self.find_and_click("提交按钮")
            _time.sleep(1)

            results.append(f"轮{r+1}: {numbers} → {solution} = 24 ✅")

            # 如果有多轮，点下一题
            if r < rounds - 1:
                self.check_cancel()
                self.find_and_click("下一题按钮")
                _time.sleep(1.5)

        summary = "\n".join(results)
        return {
            "success": True,
            "message": f"24点游戏完成！共 {rounds} 轮",
            "data": summary,
        }

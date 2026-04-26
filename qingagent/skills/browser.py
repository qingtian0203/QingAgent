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

        self.add_intent(Intent(
            name="capture_full_page",
            description="对当前浏览器打开的网页进行全页截图（使用 GoFullPage 插件），截图完成后自动下载到本地并关闭截图标签页",
            required_slots=[],
            optional_slots=[],
            examples=[
                "帮我截取这个网页",
                "把当前页面截图保存",
                "全页截图一下",
                "截图这个网页并下载",
                "用 GoFullPage 截个图",
            ],
        ))

    # --- 具体执行流程 ---

    def execute_open_url(self, slots: dict) -> dict:
        """通过 shell open 打开 URL，并等待页面加载完成再返回"""
        import time
        import subprocess

        url = slots["url"]
        # 确保有协议前缀
        if not url.startswith(("http://", "https://")):
            url = f"https://{url}"

        os.system(f'open -a "Google Chrome" "{url}"')

        # 轮询等待 Chrome 当前 Tab 加载完成（loading = false）
        # 比固定 sleep 更准确：快速页面不用等，慢速页面足够等
        print(f"🌐 打开中：{url}")
        wait_script = '''
        tell application "Google Chrome"
            if (count of windows) > 0 then
                if loading of active tab of front window then
                    return "loading"
                else
                    return "done"
                end if
            end if
        end tell
        return "no_window"
        '''
        poll_interval = 0.2
        max_wait = 30  # 最多等 30s

        # 先等 1s 让 Chrome 有时间开始加载 URL（避免检测到上一个页面的状态）
        time.sleep(1.0)

        for _ in range(int(max_wait / poll_interval)):
            try:
                result = subprocess.run(
                    ["osascript", "-e", wait_script],
                    capture_output=True, text=True, timeout=3,
                )
                status = result.stdout.strip()
                if status == "done":
                    print("✅ 页面加载完成")
                    break
                elif status == "no_window":
                    print("⚠️ Chrome 窗口未找到，继续等待...")
            except subprocess.TimeoutExpired:
                pass
            time.sleep(poll_interval)
        else:
            print("⚠️ 等待超时（30s），页面可能未完全加载")

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

    def execute_capture_full_page(self, slots: dict) -> dict:
        """
        使用 GoFullPage 插件对当前网页进行全页截图。

        流程：
        1. 激活 Chrome（保持当前 Tab 不变）
        2. 触发 GoFullPage 快捷键 ⌥⇧P
        3. AppleScript 轮询等待截图 Tab 出现（比固定 sleep 更快更可靠）
        4. Cmd+S 下载截图到本地（Chrome 直接存 Downloads，无弹窗）
        5. Cmd+W 关闭截图 Tab，回到原页面
        """
        import time
        import subprocess

        # 1. 激活浏览器
        if not self.activate():
            return {"success": False, "message": "浏览器未响应，请确保 Chrome 已打开", "data": None}

        time.sleep(0.5)

        # 2. 触发 GoFullPage（默认快捷键：Option+Shift+P）
        print("📸 触发 GoFullPage 全页截图（⌥⇧P）...")
        actions.hotkey("option", "shift", "p")

        # 3. 轮询等待 GoFullPage 截图 Tab 出现
        self.check_cancel()
        print("⏳ 等待 GoFullPage 截图完成...")

        gofullpage_tab_found = False
        poll_interval = 0.2
        max_wait = 30

        # 检测条件：URL 含扩展 ID，或 Title 含 "GoFullPage" 或 "Screenshot"
        detect_script = '''
        tell application "Google Chrome"
            repeat with w in windows
                repeat with t in tabs of w
                    set u to URL of t
                    set ttl to title of t
                    if u contains "fdpohaocaechifi" or ttl contains "GoFullPage" or ttl contains "Screenshot - GoFullPage" then
                        return "found"
                    end if
                end repeat
            end repeat
        end tell
        return "not_found"
        '''

        for _ in range(int(max_wait / poll_interval)):
            self.check_cancel()
            try:
                result = subprocess.run(
                    ["osascript", "-e", detect_script],
                    capture_output=True, text=True, timeout=3,
                )
                if "found" in result.stdout.lower():
                    gofullpage_tab_found = True
                    gofullpage_tab_found = True
                    print("✅ 截图 Tab 已出现")

                    # 调试：立刻打印所有 Tab 信息
                    debug_script2 = '''
                    tell application "Google Chrome"
                        set info to ""
                        repeat with w in windows
                            repeat with t in tabs of w
                                set info to info & (title of t) & " | " & (URL of t) & "\n"
                            end repeat
                        end repeat
                        return info
                    end tell
                    '''
                    try:
                        dr2 = subprocess.run(["osascript", "-e", debug_script2],
                                             capture_output=True, text=True, timeout=5)
                        print(f"🔍 当前所有 Tab：\n{dr2.stdout.strip()}")
                    except Exception as de:
                        print(f"🔍 Tab 列表获取失败：{de}")
                    break

            except subprocess.TimeoutExpired:
                pass
            time.sleep(poll_interval)

        if not gofullpage_tab_found:
            # 调试：打印当前所有 Tab 标题和 URL，找出实际名称
            debug_script = '''
            tell application "Google Chrome"
                set result to ""
                repeat with w in windows
                    repeat with t in tabs of w
                        set result to result & (title of t) & " | " & (URL of t) & "\n"
                    end repeat
                end repeat
                return result
            end tell
            '''
            try:
                dr = subprocess.run(["osascript", "-e", debug_script],
                                    capture_output=True, text=True, timeout=5)
                print(f"🔍 当前所有 Tab 列表：\n{dr.stdout.strip()}")
            except Exception:
                pass
            return {
                "success": False,
                "message": "⚠️ 等待超时，GoFullPage 截图 Tab 未出现",
                "data": None,
            }

        # 4. 轮询等 GoFullPage Tab URL 含 ?（只查，不激活，避免 index of t 出错）
        print("⏳ 等待 GoFullPage Tab 内容就绪...")
        wait_ready_script = '''
        tell application "Google Chrome"
            repeat with w in windows
                repeat with t in tabs of w
                    set u to URL of t
                    set ttl to title of t
                    if u contains "fdpohaocaechifi" or ttl contains "GoFullPage" or ttl contains "Screenshot - GoFullPage" then
                        if u contains "?" then
                            return "ready"
                        else
                            return "loading"
                        end if
                    end if
                end repeat
            end repeat
        end tell
        return "not_found"
        '''

        # 激活脚本单独跑（和 URL 检查分开，避免 set active tab index 出错）
        activate_gofullpage_script = '''
        tell application "Google Chrome"
            set tabIdx to 0
            repeat with w in windows
                set tabIdx to 0
                repeat with t in tabs of w
                    set tabIdx to tabIdx + 1
                    set u to URL of t
                    set ttl to title of t
                    if u contains "fdpohaocaechifi" or ttl contains "GoFullPage" or ttl contains "Screenshot - GoFullPage" then
                        set active tab index of w to tabIdx
                        set index of w to 1
                        activate
                        return "activated"
                    end if
                end repeat
            end repeat
        end tell
        return "not_found"
        '''

        tab_ready = False
        for _ in range(50):   # 最多等 10s
            self.check_cancel()
            try:
                rw = subprocess.run(["osascript", "-e", wait_ready_script],
                                    capture_output=True, text=True, timeout=5)
                status = rw.stdout.strip()
                if status == "ready":
                    tab_ready = True
                    print("✅ GoFullPage Tab 内容就绪，准备激活并复制")
                    # 单独激活
                    subprocess.run(["osascript", "-e", activate_gofullpage_script],
                                   capture_output=True, text=True, timeout=5)
                    break
                elif status == "loading":
                    pass
                elif status == "not_found":
                    pass
                else:
                    print(f"⚠️ Tab 状态异常：'{status}' stderr={rw.stderr.strip()[:80]}")
            except subprocess.TimeoutExpired:
                pass
            time.sleep(0.2)

        if not tab_ready:
            print("⚠️ 等待超时，Tab 未就绪，仍尝试继续...")

        # 5. Cmd+C —— GoFullPage Tab 已激活，复制截图到剪贴板
        print("📋 Cmd+C 复制截图到剪贴板...")
        actions.hotkey("command", "c")
        time.sleep(1.2)

        # 6. 把剪贴板 PNG 存盘，供 screenshot_path 使用
        import os as _os
        from datetime import datetime as _dt
        timestamp = _dt.now().strftime("%Y%m%d_%H%M%S")
        save_path = f"/tmp/qingagent_fullpage_{timestamp}.png"
        save_clip_script = f'''
        try
            set fileRef to open for access POSIX file "{save_path}" with write permission
            write (the clipboard as «class PNGf») to fileRef
            close access fileRef
            return "ok"
        on error e
            return "err:" & e
        end try
        '''
        new_file = None
        try:
            r2 = subprocess.run(["osascript", "-e", save_clip_script],
                                capture_output=True, text=True, timeout=8)
            out2 = r2.stdout.strip()
            if out2 == "ok" and _os.path.exists(save_path) and _os.path.getsize(save_path) > 1000:
                new_file = save_path
                print(f"💾 截图已存盘：{new_file}")
            else:
                print(f"⚠️ 存盘失败：{out2}")
        except Exception as e:
            print(f"⚠️ 存盘异常：{e}")

        # 7. 精准关闭 GoFullPage Tab（按 URL 找，不依赖焦点）
        self.check_cancel()
        print("🗑️ 关闭 GoFullPage Tab...")
        close_tab_script = '''
        tell application "Google Chrome"
            set tabIdx to 0
            repeat with w in windows
                set tabIdx to 0
                repeat with t in tabs of w
                    set tabIdx to tabIdx + 1
                    set u to URL of t
                    set ttl to title of t
                    if u contains "fdpohaocaechifi" or ttl contains "GoFullPage" or ttl contains "Screenshot - GoFullPage" then
                        set active tab index of w to tabIdx
                        close t
                        return "closed"
                    end if
                end repeat
            end repeat
        end tell
        return "not_found"
        '''
        subprocess.run(["osascript", "-e", close_tab_script],
                       capture_output=True, text=True, timeout=5)
        time.sleep(0.3)

        if new_file:
            msg = f"✅ 全页截图已复制到剪贴板并存盘：{new_file}"
        else:
            msg = "✅ 全页截图已复制到剪贴板（可直接粘贴）"

        return {
            "success": True,
            "message": msg,
            "data": {"screenshot_path": new_file} if new_file else None,
        }


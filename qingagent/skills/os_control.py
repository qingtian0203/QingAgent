from __future__ import annotations

import time
from .base import BaseSkill, Intent
from qingagent.core import actions, vision

class OSControlSkill(BaseSkill):
    app_name = "System"
    app_aliases = ["系统", "屏幕", "系统控制", "电脑"]
    app_context = "电脑整个屏幕"

    def register_intents(self):
        self.add_intent(Intent(
            name="custom_screenshot",
            description="截取【当前已在屏幕上可见的】某个具体元素、图表或局部区域。注意：如果用户要求给某个特定的【应用程序/软件】截图，请绝对不要用这个意图，而应该用 app_screenshot",
            required_slots=["target"],
            examples=[
                "帮我截取屏幕左侧的导航栏",
                "把下面那个表格用截图工具保存",
                "截取右边的那张海报图片"
            ],
        ))
        
        self.add_intent(Intent(
            name="app_screenshot",
            description="给某个指定的【应用程序/软件】截图（例如备忘录、微信、日历、系统设置等）。当你识别到目标是一个软件应用时，必须强制使用本意图，因为它负责把被后台遮挡的软件拉到最前面再进行截图。",
            required_slots=["app_name"],
            examples=[
                "给微信截图",
                "帮我把备忘录内容截图发一下",
                "截取系统设置界面",
                "用截图软件将日历保存"
            ],
        ))

        self.add_intent(Intent(
            name="open_app",
            description="打开、启动或切换到某个指定的应用程序/软件。用户说'打开xx'、'启动xx'、'切换到xx'、'进入xx'时使用，xx 就是应用名称。",
            required_slots=["app_name"],
            examples=[
                "打开微信",
                "帮我打开备忘录",
                "启动 Safari",
                "打开系统设置",
                "打开晴天Util",
                "切换到日历",
                "进入 Xcode",
                "帮我打开终端",
            ],
        ))

        self.add_intent(Intent(
            name="prepare_file",
            description="搜寻并准备要发送/上传的文件。如果用户明确指出了文件的所在位置（如 桌面的/下载里的/文稿里的），**必须**将其提取到 search_dir 参数中。如果用户提供的是带有前缀 '/' 的长绝对路径，直接将其作为 filename。如果是普通的模糊名字（如'年度报表'），将使用系统底层引擎全文检索。",
            required_slots=["filename"],
            optional_slots=["search_dir"],
            examples=[
                "帮我把桌面的 某某测试文档 找出来",
                "找到下载中的作业",
                "发这个绝对路径的文件: /Users/konglingjia/Desktop/A.pdf",
                "搜一下年度报表",
            ]
        ))

        # 网页全页截图兜底路由：小模型可能误路由到 System，这里委托给浏览器处理
        self.add_intent(Intent(
            name="capture_full_page",
            description="使用 GoFullPage 对当前浏览器页面进行全页截图并下载，截图后返回文件路径",
            required_slots=[],
            optional_slots=[],
            examples=[
                "截图当前网页",
                "全页截图",
                "把网页截图下载",
            ],
        ))

    def activate(self) -> bool:
        """重写激活逻辑，由于是 OS 全局控制，操作平面设定为整块物理主屏幕"""
        import pyautogui
        screen_w, screen_h = pyautogui.size()
        # 将整个屏幕作为一个巨大的"虚拟窗口"框定
        self._window_rect = (0, 0, screen_w, screen_h)
        return True

    def execute_open_app(self, slots: dict) -> dict:
        """打开/激活指定应用程序"""
        app_name = slots.get("app_name", "").strip()
        if not app_name:
            return {"success": False, "message": "请告诉我要打开哪个应用", "data": None}

        print(f"🚀 [打开应用] 目标：{app_name}")

        from qingagent.core.window import resolve_app_real_name, activate_app

        # 智能解析应用名（支持中文alias，如"备忘录"→"Notes"、"微信"→"WeChat"）
        actual_name = resolve_app_real_name(app_name)
        print(f"  → 解析为系统应用名：{actual_name}")

        try:
            activate_app(actual_name, resolved=True)
            time.sleep(1.2)  # 等待系统动画完成
            return {
                "success": True,
                "message": f"✅ 已打开 {app_name}",
                "data": {"app_name": app_name, "resolved_name": actual_name},
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"打开 {app_name} 失败：{e}",
                "data": None,
            }

    def execute_custom_screenshot(self, slots: dict) -> dict:
        """执行自定义抠图截屏（长按并拖拽划虚线框）"""
        if not self.activate():
            return {"success": False, "message": "无法初始化全屏环境", "data": None}
            
        target = slots["target"]
        print(f"🖥️ [通用控制] 准备执行系统截屏，目标内容：{target}")

        # 1. 在当前物理界面上做一次无干扰全屏截图作为感知基础
        # QQ 截图还没启动，当前界面是干净的
        baseline_img = self.screenshot()
        if not baseline_img:
            return {"success": False, "message": "无法截取底图做感知", "data": None}

        # 2. 调用新增的 Bounding Box 能力查找目标的四角顶点
        bounds = vision.find_element_bounds(baseline_img, target, context="用户的电脑屏幕全景")
        if not bounds:
            return {"success": False, "message": f"视觉引擎找不到目标区域：{target}", "data": None}

        # 构建画框的起止点比例坐标
        start_pt = {"rx": bounds["rx1"], "ry": bounds["ry1"]}
        end_pt = {"rx": bounds["rx2"], "ry": bounds["ry2"]}

        # 为了更符合人类选框视觉，可以适度进行坐标外扩和内缩（目前选用精准贴边）
        # 让框宽以保护文字不被切碎
        start_pt["rx"] = max(0, start_pt["rx"] - 5)
        start_pt["ry"] = max(0, start_pt["ry"] - 5)
        end_pt["rx"] = min(1000, end_pt["rx"] + 5)
        end_pt["ry"] = min(1000, end_pt["ry"] + 5)

        # 3. 唤醒 QQ 截图 (macOS 系统热键：Ctrl + Cmd + A)
        print("⌨️ 触发截图热键 (Ctrl+Cmd+A)...")
        actions.hotkey("ctrl", "command", "a")
        
        # 给 QQ 截屏遮罩弹出的动画时间
        time.sleep(1.0) 

        # 4. 执行划破天空的“左键长按+拖拽拉伸”微操画框动作
        print(f"🖱️ 模拟人类滑动选取边界框...")
        # 此处的 target_rect 传整个屏幕尺寸
        target_rect = getattr(self, '_last_screenshot_rect', self._window_rect)
        actions.drag_normalized(target_rect, start_pt, end_pt, duration=1.5)

        # 5. 终极双保险确认法：计算截图框的中心点，先在框内双击（所有截图工具通用），再补一个回车！
        center_pt = {
            "rx": (start_pt["rx"] + end_pt["rx"]) // 2,
            "ry": (start_pt["ry"] + end_pt["ry"]) // 2
        }
        
        # 给 QQ 渲染拖框动画的缓冲时间（防止按键吞丢）
        time.sleep(0.5) 
        print("🖱️ 移动回画框中心点执行通用双击确认，并敲击回车兜底...")
        
        # 绝大多数截屏软件（包括 Mac 自带）支持“在选框中心双击直接完成并拷贝”
        actions.double_click_at_normalized(target_rect, center_pt)
        time.sleep(0.5)
        # QQ 截屏在没开特定设置时，也能用回车收尾
        actions.press_key("enter")
        time.sleep(0.5)

        # 把剪贴板图片保存到磁盘，供后续步骤 ${stepN.screenshot_path} 引用
        screenshot_path = self._save_clipboard_image()
        return {
            "success": True,
            "message": "截图成功（已双击/回车双重确认）",
            "data": {
                "target": target,
                "screenshot_path": screenshot_path,
            }
        }

    def execute_app_screenshot(self, slots: dict) -> dict:
        """
        利用 QQ 截图/Mac原生截图 的窗口自动吸附功能，对指定后台应用进行丝滑全窗截取
        """
        app_name = slots.get("app_name")
        if not app_name:
            return {"success": False, "message": "缺少应用名称"}
            
        # 确保 OS 层面的屏幕矩形区域已被顺利激活（防止跨意图调用时生命周期没带上 _window_rect 引发 NoneType 报错）
        if not self._window_rect:
            self.activate()
            
        print(f"🚀 准备为应用 [{app_name}] 执行全窗口截图...")
        
        from qingagent.core.window import resolve_app_real_name
        
        import time as _time
        t_start = _time.time()
        # 1. 动态智能解析
        actual_mac_app_name = resolve_app_real_name(app_name)
        print(f"⏱️ [探针] resolve_app_real_name 耗时: {_time.time() - t_start:.2f}s")
        
        t0 = _time.time()
        # 2. 召唤 APP 
        from qingagent.core import window
        print(f"🪄 使用 QingAgent 统一的 window.activate_app 召唤 {actual_mac_app_name} 到台前...")
        window.activate_app(actual_mac_app_name, resolved=True)
        
        # 极致压缩系统前台弹跳休眠：高配机器完全无需 1.5s，0.3s 足矣
        time.sleep(0.3)
        print(f"⏱️ [探针] activate_app 及动画休眠耗时: {_time.time() - t0:.2f}s")
            
        # 2. 提取物理边界
        t0 = _time.time()
        print(f"📷 正在通过本地 Quartz API 瞬发检索 {actual_mac_app_name} 窗口物理边界...")
        win = window.find_window([actual_mac_app_name, app_name])
        if not win:
            return {"success": False, "message": f"系统底层未找到 {app_name} 对应的窗口句柄，可能已被隐藏或最小化", "data": app_name}
        
        # 计算该应用窗口在屏幕上的绝对中心坐标
        win_rect = win["rect"]  # (x, y, w, h)
        abs_cx = win_rect[0] + win_rect[2] / 2
        abs_cy = win_rect[1] + win_rect[3] / 2
        print(f"⏱️ [探针] Quartz 搜寻窗口坐标耗时: {_time.time() - t0:.2f}s")
        
        # 3. 开始边缘计算
        t0 = _time.time()
        target_rect = getattr(self, '_last_screenshot_rect', self._window_rect)
        norm_x = (abs_cx - target_rect[0]) / target_rect[2]
        norm_y = (abs_cy - target_rect[1]) / target_rect[3]
        center_pt = {
            "rx": int(norm_x * 1000),
            "ry": int(norm_y * 1000)
        }
        
        # 将光标极速瞬移过去（穿透默认 duration=0.5s 的束缚）
        actions.move_to(target_rect, center_pt, duration=0.05)
        time.sleep(0.1) 
        
        # 触发截图结界 (Ctrl+Cmd+A)...
        actions.hotkey("ctrl", "command", "a", delay=0.1)
        time.sleep(0.4) # 必须给系统截图遮罩一个展开变黑的时间
        
        # 单击边缘吸附（强制覆盖 actions 库中默认的 0.6s ACTION_DELAY 死亡停顿）
        actions.click_at_normalized(target_rect, center_pt, delay=0.05)
        time.sleep(0.05) 
        
        # 收网：双击+回车
        actions.double_click_at_normalized(target_rect, center_pt, delay=0.05)
        time.sleep(0.05)
        actions.press_key("enter", delay=0.05)
        time.sleep(0.1) 
        print(f"⏱️ [探针] 键盘鼠标截屏六连击耗时: {_time.time() - t0:.2f}s")

        t0 = _time.time()
        # 把剪贴板图片保存到磁盘
        screenshot_path = self._save_clipboard_image()
        print(f"⏱️ [探针] _save_clipboard_image 存盘耗时: {_time.time() - t0:.2f}s")
        print(f"🔥 [探针] System.app_screenshot 方法栈内总计真耗时: {_time.time() - t_start:.2f}s")
        return {
            "success": True,
            "message": f"行云流水！已对 {app_name} 触发独立窗口吸附截取",
            "data": {
                "app_name": app_name,
                "screenshot_path": screenshot_path,
            }
        }

    def _save_clipboard_image(self) -> str | None:
        """
        把当前系统剪贴板里的图片保存到磁盘文件。
        截图工具（QQ截图/Mac原生截图）完成后会把图片放入剪贴板。

        返回：
            保存成功 → 图片路径（如 /tmp/qingagent_screenshot_20240101_120000.png）
            剪贴板无图片 → None
        """
        import subprocess
        import os
        from datetime import datetime

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        save_path = f"/tmp/qingagent_screenshot_{timestamp}.png"

        try:
            # 方案 A：用 AppleScript 把剪贴板 PNG 数据写入文件
            script = f"""
set theFile to POSIX file "{save_path}"
set fileRef to open for access theFile with write permission
write (the clipboard as «class PNGf») to fileRef
close access fileRef
"""
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode == 0 and os.path.exists(save_path) and os.path.getsize(save_path) > 0:
                print(f"💾 截图已保存：{save_path}")
                return save_path

            # 方案 B：用 pngpaste（需要 brew install pngpaste）
            alt = subprocess.run(["pngpaste", save_path], capture_output=True, timeout=5)
            if alt.returncode == 0 and os.path.exists(save_path):
                print(f"💾 截图已保存（pngpaste）：{save_path}")
                return save_path

            print("⚠️ 剪贴板无图片数据，截图可能仍在剪贴板中（可用 [粘贴] 直接发送）")
            return None

        except Exception as e:
            print(f"⚠️ 保存剪贴板图片出错：{e}")
            return None

    def execute_prepare_file(self, slots: dict) -> dict:
        import subprocess
        import os
        
        filename = slots.get("filename", "")
        # 支持绝对路径直通！
        if filename.startswith("/"):
            if os.path.exists(filename):
                return self._copy_file_to_clipboard(filename)
            else:
                return {"success": False, "message": f"哎呀，这个绝对路径不存在了：{filename}"}

        search_dir = slots.get("search_dir", "")
        
        # 语义换算
        dir_mapping = {
            "桌面": os.path.expanduser("~/Desktop"),
            "下载": os.path.expanduser("~/Downloads"),
            "文档": os.path.expanduser("~/Documents"),
            "文稿": os.path.expanduser("~/Documents"),
        }
        
        target_dir = ""
        for key, path in dir_mapping.items():
            if search_dir and key in search_dir:
                target_dir = path
                break
                
        cmd = ["mdfind"]
        if target_dir:
            cmd.extend(["-onlyin", target_dir])
        cmd.extend(["-name", filename])
        
        print(f"🕵️ 正在用 Spotlight 引擎海底搜罗：{' '.join(cmd)}")
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        except Exception as e:
            return {"success": False, "message": f"搜索系统出错：{e}"}
            
        lines = [line.strip() for line in result.stdout.split("\n") if line.strip()]
        
        # 过滤
        lines = [lf for lf in lines if "/Library/" not in lf and "/.Trash/" not in lf and "/System/" not in lf and ".app/" not in lf]
        
        if len(lines) == 0:
            return {"success": False, "message": f"未能在全系统扫描范围内找到包含【{filename}】的文件。"}
        
        if len(lines) == 1:
            print(f"🎯 唯一精确命中：{lines[0]}")
            return self._copy_file_to_clipboard(lines[0])
            
        # 批量冲突
        top_k = lines[:10]
        items = [{ "name": os.path.basename(p), "path": p } for p in top_k]
            
        print(f"⚖️ 命中 {len(lines)} 个相关文件，将触发前端阻击确认名单！")
        return {
            "success": False,
            "message": f"为了防止弄错，我帮您检索到了多个相似的文件，请在下方列表点击选择：",
            "data": {
                "type": "file_choice",
                "items": items
            }
        }

    def _copy_file_to_clipboard(self, filepath: str) -> dict:
        import subprocess
        script = f'set the clipboard to POSIX file "{filepath}"'
        try:
            subprocess.run(["osascript", "-e", script])
            print(f"📋 幽灵载入：文件 {filepath} 已灌入物理剪贴板！")
            return {
                "success": True,
                "message": f"文件锁具确认，已装填入剪贴板发射舱准备接续动作：{filepath}",
                "data": {
                    "file_path": filepath
                }
            }
        except Exception as e:
            return {"success": False, "message": f"尝试装填到剪贴板失败：{e}"}

    def execute_capture_full_page(self, slots: dict) -> dict:
        """委托给 BrowserSkill 执行网页全页截图（小模型误路由到 System 时的兜底）"""
        from .browser import BrowserSkill
        print("🔀 System.capture_full_page → 委托给 BrowserSkill.capture_full_page")
        return BrowserSkill().execute_capture_full_page(slots)

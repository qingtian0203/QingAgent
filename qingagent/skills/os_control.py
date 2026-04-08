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

    def activate(self) -> bool:
        """重写激活逻辑，由于是 OS 全局控制，操作平面设定为整块物理主屏幕"""
        import pyautogui
        screen_w, screen_h = pyautogui.size()
        # 将整个屏幕作为一个巨大的"虚拟窗口"框定
        self._window_rect = (0, 0, screen_w, screen_h)
        return True

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
        
        # 1. 动态智能解析，彻底丢弃死板的中英文映射表！
        # 输入 "备忘录" -> 秒级返回 "Notes"
        actual_mac_app_name = resolve_app_real_name(app_name)
        
        # 2. 直接越过系统权限，强行把后台乃至关闭窗口的 APP 弹跳唤醒到最上层！
        from qingagent.core import window
        print(f"🪄 使用 QingAgent 统一的 window.activate_app 召唤 {actual_mac_app_name} 到台前...")
        window.activate_app(actual_mac_app_name, resolved=True)
        
        # 等待系统的动画展开：如果本身就是没开着的，多给点时间
        time.sleep(1.5)
            
        # 2. 洗牌后的整个电脑屏幕合影，找寻主目标！
        print(f"📷 正在启动天眼全景透视，寻找 {app_name} 落在视野内的重心...")
        baseline_img = self.screenshot()
        if not baseline_img: # 严格阻断
            return {"success": False, "message": "底座截图模块崩溃，未能获取屏幕像素"}
            
        center_pt = vision.find_element_with_retry(baseline_img, f"最前方的主窗口、具有 {app_name} 界面特征的应用主结构")
        
        if not center_pt:
            return {"success": False, "message": f"视觉引擎已扫描三遍，桌面似乎未被 {app_name} 占据", "data": app_name}
            
        # 3. 开始表演：利用截图软件的边缘计算白嫖法！
        target_rect = getattr(self, '_last_screenshot_rect', self._window_rect)
        
        # 先把鼠标幽灵般地挪过去，轻轻盖在目标头上
        print(f"🖱️ 将光标悬停在 {app_name} 的视窗重心...")
        actions.move_to(target_rect, center_pt)
        time.sleep(0.3)
        
        # 打开系统黑魔法（触发截图工具）
        print("⌨️ 触发截图结界 (Ctrl+Cmd+A)...")
        actions.hotkey("ctrl", "command", "a")
        time.sleep(0.8) # 注意：这一步截图边框正在做 OS 层面的边框查找，必等
        
        # 单击降维打击（此时截图软件会自动因为鼠标位置吸附该应用周围一圈的边框）
        print("🖱️ 窗体已变黑变暗，执行原点单击（吸附并套牢边框）...")
        actions.click_at_normalized(target_rect, center_pt)
        time.sleep(0.3)
        
        # 收网
        print("🖱️ 收网！中心双击并回车确认...")
        actions.double_click_at_normalized(target_rect, center_pt)
        time.sleep(0.3)
        actions.press_key("enter")
        time.sleep(0.5)

        # 把剪贴板图片保存到磁盘，供后续步骤 ${stepN.screenshot_path} 引用
        screenshot_path = self._save_clipboard_image()
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

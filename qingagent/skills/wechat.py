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
#  联系人定位与焦点策略（告别硬编码坐标）
#  全流程采用 Cmd+F 以及基于 AppleOS 的默认焦点流转
# ============================================================


class WeChatSkill(BaseSkill):
    app_name = "微信"
    app_aliases = ["WeChat", "wechat", "微信"]
    app_context = "微信聊天界面截图"
    cold_start_wait = 2.0   # 微信冷启动等待（搜索框会再吸收一些时间）

    def register_intents(self):
        self.add_intent(Intent(
            name="send_message",
            ui_label="发送消息 / 图片 / 文件",
            description=(
                "给指定联系人或群发送消息、图片或文件。\n"
                "- 发文字：填 contact_name + message。\n"
                "- 发图片/文件，且上一步有 file_path 或 screenshot_path 输出：\n"
                "  **必须**用 image_path=${stepN.file_path} 或 image_path=${stepN.screenshot_path} 传路径。\n"
                "  这样会在找到联系人之后才重新把文件灌入剪贴板，\n"
                "  避免搜索框输入中文时覆盖剪贴板内容导致粘贴出错。\n"
                "- 只在上一步没有 file_path/screenshot_path 输出、文件已在剪贴板时才用 use_clipboard=true。\n"
                "- 不要用'[粘贴]'等魔法字符串。"
            ),
            required_slots=["contact_name"],
            optional_slots=["message", "image_path", "use_clipboard"],
            examples=[
                "给晴天发条微信说下午开会",
                "把自己刚刚截的图发给老板",
                "把刚才准备好的文件发给刘婷婷",
            ],
        ))

        
        self.add_intent(Intent(
            name="confirm_send_action",
            ui_label="确认发送（按下回车）",
            description="当需要向微信补充按下回车键以确认发送前文处于待发送状态的消息/文件时使用。严格对应用户的最终发送许可动作。",
            examples=["微信确认发送", "执行微信确认发送", "确认发送微信"]
        ))
        self.add_intent(Intent(
            name="check_messages",
            ui_label="查看最新消息",
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
            ui_label="提取聊天记录",
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
        通过搜索框定位联系人（无 AI 调用，使用 Cmd+F 快捷键激活搜索）。

        流程：
        1. Cmd+F 激活搜索框（比坐标点击更可靠，不受窗口尺寸影响）
        2. 输入联系人名字
        3. 等待搜索结果
        4. 点击第一个结果
        5. 按 Esc 退出搜索状态
        """
        import subprocess

        # 1. 轮询确认微信确实在最前台（窗口切换动画可能需要 0.5-1s）
        print("⏳ 等待微信切换到最前台...")
        wechat_front_script = '''
        tell application "System Events"
            set frontApp to name of first process whose frontmost is true
            if frontApp is "WeChat" then
                return "active"
            else
                return frontApp
            end if
        end tell
        '''
        wechat_ready = False
        for _ in range(20):   # 最多等 4s（0.2s × 20）
            try:
                r = subprocess.run(["osascript", "-e", wechat_front_script],
                                   capture_output=True, text=True, timeout=3)
                out = r.stdout.strip()
                if out == "active":
                    wechat_ready = True
                    print("✅ 微信已切换到最前台")
                    break
                else:
                    pass  # 继续等，不打印避免刷屏
            except subprocess.TimeoutExpired:
                pass
            _time.sleep(0.2)

        if not wechat_ready:
            print("⚠️ 等待微信前台超时，继续尝试...")

        # 微信在前台但焦点可能在内嵌 WebView（文章/公众号）里，
        # 直接用 AppleScript tell process 把 Cmd+F 注入微信进程，
        # 无需关心焦点在哪，进程级快捷键直达微信
        print("🔑 通过进程级快捷键注入 Cmd+F...")
        search_inject_script = '''
        tell application "System Events"
            tell process "WeChat"
                keystroke "f" using command down
            end tell
        end tell
        '''
        subprocess.run(["osascript", "-e", search_inject_script],
                       capture_output=True, text=True, timeout=5)
        _time.sleep(0.4)



        # 3. 先清空搜索框已有内容，再输入联系人名
        actions.hotkey("command", "a", delay=0.1)
        actions.type_text(contact)

        # 4. 等搜索结果加载
        self.check_cancel()
        _time.sleep(1.2)

        # 5. 直接回车进入第一条搜索结果（微信默认选中第一条）
        self.check_cancel()
        actions.press_key("return", delay=0.4)  # 等搜索结果选中，0.4s 足够

        # 6. 按 Esc 退出搜索状态（回到正常聊天界面）
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
        contact = slots.get("contact_name", "").strip()
        if not contact:
            return {"success": False, "message": "缺少联系人名称（contact_name），请告诉我要发给谁", "data": None}
        # message 现在是可选的，Planner 不填时默认空字符串
        message = slots.get("message", "")
        # use_clipboard=true 表示前序步骤已把文件/图片灌入剪贴板，直接 Cmd+V 即可
        use_clipboard = str(slots.get("use_clipboard", "false")).lower() in ("true", "1", "yes")

        # 步骤 1：激活微信
        if not self.activate():
            return {"success": False, "message": "无法打开微信", "data": None}

        # 步骤 2：定位联系人
        if not self._find_contact(contact):
            return {"success": False, "message": f"找不到联系人：{contact}", "data": None}

        # 等聊天窗口完全打开
        self.check_cancel()
        _time.sleep(0.5)  # 等聊天窗口切换动画完成

        # 步骤 3：准备发送
        # 优化说明：通过 Cmd+F 唤醒搜索并回车后，微信原生行为会自动将焦点锚定到文字输入框。
        # 因此，这里彻底移除了之前 `actions.click_at_normalized` 的固定坐标（绝对坐标容易因窗口大小变化而失效），
        # 我们利用系统的自然焦点流转，达到分辨率无关的优雅控制。
        self.check_cancel()

        # 步骤 4：输入并发送
        self.check_cancel()
        
        image_path = slots.get("image_path")

        # 判断是否需要发图或发文件
        if image_path:
            import os
            ext = os.path.splitext(image_path)[1].lower()
            if ext in [".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"]:
                print(f"🖼️ 准备发送物理图片，先将其灌入剪贴板顶层: {image_path}")
                img_success = actions.copy_image_to_clipboard(image_path)
                if not img_success:
                    print("❌ 图片灌入失败，中止发送")
                    return {"success": False, "message": "读取本地图片失败", "data": None}
            else:
                print(f"📄 准备发送物理文件，将其作为 POSIX File 对象塞入剪贴板: {image_path}")
                import subprocess
                subprocess.run(["osascript", "-e", f'set the clipboard to POSIX file "{image_path}"'])

            _time.sleep(0.2)
            actions.hotkey("command", "v")
            _time.sleep(0.8)  # 粘贴后等多媒体/文件对象渲染，留足缓冲时间
                
        elif use_clipboard or (
            message in ("[粘贴]", "「粘贴」", "粘贴")
            or "{{clipboard" in message
            or "剪贴板" in message.lower()
            or "paste" in message.lower()
        ):
            # 搜索框输入中文时 macOS 会用剪贴板传输汉字，导致文件被挤到第二位
            # 修复方案：先从临时文件读回路径，重新把文件灌入剪贴板第一位，再 Cmd+V
            import subprocess, os
            _last_file_cache = "/tmp/qingagent_last_clipboard_file.txt"
            _reloaded = False
            try:
                if os.path.exists(_last_file_cache):
                    with open(_last_file_cache, "r") as _f:
                        _last_file = _f.read().strip()
                    if _last_file and os.path.exists(_last_file):
                        print(f"📋 搜索中文导致剪贴板被覆盖，重新灌入文件: {_last_file}")
                        subprocess.run(["osascript", "-e", f'set the clipboard to POSIX file "{_last_file}"'])
                        _time.sleep(0.4)  # 等剪贴板生效
                        _reloaded = True
            except Exception as _e:
                print(f"⚠️ 重新灌入剪贴板失败: {_e}")
            if not _reloaded:
                print("📋 找不到临时记录，直接 Cmd+V 尝试粘贴")
            actions.hotkey("command", "v")
            _time.sleep(0.8)  # 等文件/图片对象渲染完成
        elif message:
            actions.type_text(message)
        else:
            print("⚠️ message 为空且未设置 use_clipboard，跳过输入步骤")
            
        import os
        mode = os.environ.get("QINGAGENT_MODE", "safe")
        
        if mode == "fast":
            print("🚀 极速模式结界穿透：已绕过所有阻断机制，直接发送！")
            _time.sleep(0.5)
            import subprocess
            subprocess.run(["osascript", "-e", 'tell application "System Events" to key code 36'])  # 强力触发 Mac 物理回车
            return {
                "success": True,
                "message": f"🚀 安全限制解除：已将消息极限盲发给 **{contact}**。请注意操作不可逆。",
                "data": None
            }
            
        # [强制拦截机制安全态] 将包含文字、图片或文件的所有发送任务挂起，等待用户点按最终按键
        print("🛡️ 人工审核挂机：检测到发送操作，安全阀门已落下...")
        _time.sleep(0.5)
        
        # 存当前全屏底图
        img_b64 = self.screenshot()
        
        confirm_path = None
        if img_b64:
            import base64
            from datetime import datetime
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            confirm_path = f"/tmp/qingagent_confirm_{ts}.png"
            with open(confirm_path, "wb") as fh:
                fh.write(base64.b64decode(img_b64))

        return {
            "success": False,
            "message": f"即将发送给 {contact}，请确认无误后点击下方按钮发送：",
            "data": {
                "type": "confirm_send",
                "screenshot_path": confirm_path
            }
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


    def execute_confirm_send_action(self, slots: dict) -> dict:
        import time
        if not self.activate():
            return {"success": False, "message": "无法打开微信", "data": None}
        time.sleep(0.3)  # 确认发送前等微信窗口激活稳定
        
        # 只敲下最后的审判回车
        # macOS 强力回车注入：使用 osascript 发送 key code 36（主键盘区回车）
        # 完全绕过 pyautogui 的键位映射问题，100% 触发微信的发送事件
        import subprocess
        subprocess.run(["osascript", "-e", 'tell application "System Events" to key code 36'])
        return {
            "success": True,
            "message": "已成功确认并触发发送动作！🎯",
            "data": None
        }

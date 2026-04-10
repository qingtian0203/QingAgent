"""
WebUISkill — 控制 QingAgent Web 界面自身的技能。

支持的操作：
  - hard_reload : 清除浏览器缓存并强制刷新页面
  - open_web    : 在浏览器打开 QingAgent Web 控制台
"""

import subprocess
import webbrowser
from .base import BaseSkill, Intent
from .. import config


class WebUISkill(BaseSkill):
    """控制 QingAgent Web 界面的技能。"""

    # ── 标识 ──────────────────────────────────────────────────────
    app_name    = "WebUI"
    app_aliases = [
        "WebUI", "web", "Web", "界面", "页面", "控制台",
        "QingAgent页面", "Agent界面", "刷新页面",
    ]
    app_context = "QingAgent Web 控制台界面"

    # ── Web 地址 ──────────────────────────────────────────────────
    @property
    def _web_url(self) -> str:
        return f"http://localhost:{config.SERVER_PORT}"

    # ── 注册意图 ──────────────────────────────────────────────────
    def register_intents(self):
        self.add_intent(Intent(
            name="hard_reload",
            description="清除浏览器缓存并强制刷新 QingAgent 页面，解决修改样式/JS 后不生效的问题",
            required_slots=[],
            optional_slots=[],
            examples=[
                "刷新一下页面",
                "清除缓存刷新",
                "强刷页面",
                "帮我刷新 QingAgent 界面",
                "页面修改了不生效，帮我刷新",
            ],
        ))

        self.add_intent(Intent(
            name="open_web",
            description="在浏览器中打开 QingAgent Web 控制台",
            required_slots=[],
            optional_slots=[],
            examples=[
                "打开 QingAgent 页面",
                "在浏览器打开控制台",
                "打开 Agent 界面",
            ],
        ))

    # ── 执行方法 ──────────────────────────────────────────────────

    def execute_hard_reload(self, slots: dict) -> dict:
        """
        通过 AppleScript 控制浏览器执行硬刷新（Cmd+Shift+R），
        强制跳过缓存重新加载 QingAgent 页面。
        """
        url = self._web_url

        # 1. 尝试用 AppleScript 控制已打开的 Safari / Chrome / Arc
        browsers = [
            ("Safari",          self._reload_safari),
            ("Google Chrome",   self._reload_chrome),
            ("Arc",             self._reload_chrome_like("Arc")),
        ]

        for browser_name, reload_fn in browsers:
            try:
                result = reload_fn(url)
                if result:
                    return {
                        "success": True,
                        "message": f"✅ 已在 {browser_name} 中清缓存强刷 {url}",
                        "data": None,
                    }
            except Exception:
                continue

        # 2. 兜底：直接用 webbrowser 打开带时间戳的 URL（强制绕过缓存）
        import time
        bust_url = f"{url}?_t={int(time.time())}"
        webbrowser.open(bust_url)
        return {
            "success": True,
            "message": f"✅ 已在浏览器打开（带缓存破坏参数）：{bust_url}",
            "data": None,
        }

    def execute_open_web(self, slots: dict) -> dict:
        """在浏览器中打开 QingAgent Web 控制台。"""
        url = self._web_url
        webbrowser.open(url)
        return {
            "success": True,
            "message": f"✅ 已在浏览器打开 {url}",
            "data": None,
        }

    # ── 内部辅助 ──────────────────────────────────────────────────

    def _reload_safari(self, url: str) -> bool:
        """AppleScript 控制 Safari 强刷（Cmd+Option+R）。"""
        script = f'''
        tell application "Safari"
            activate
            repeat with w in windows
                repeat with t in tabs of w
                    if URL of t contains "{url.replace('"', '')}" then
                        set current tab of w to t
                        tell application "System Events"
                            key code 15 using {{command down, option down}}
                        end tell
                        return true
                    end if
                end repeat
            end repeat
        end tell
        return false
        '''
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True, text=True, timeout=5,
        )
        return "true" in result.stdout.lower()

    def _reload_chrome(self, url: str) -> bool:
        """AppleScript 控制 Chrome 强刷（Cmd+Shift+R）。"""
        return self._reload_chrome_like("Google Chrome")(url)

    def _reload_chrome_like(self, app_name: str):
        """工厂方法：生成针对 Chromium 系浏览器的强刷函数。"""
        def _reload(url: str) -> bool:
            script = f'''
            tell application "{app_name}"
                activate
                set found to false
                repeat with w in windows
                    repeat with t in tabs of w
                        if URL of t contains "{url.replace('"', '')}" then
                            set active tab index of w to tab index of t
                            set index of w to 1
                            tell application "System Events"
                                key code 15 using {{command down, shift down}}
                            end tell
                            set found to true
                            exit repeat
                        end if
                    end repeat
                    if found then exit repeat
                end repeat
            end tell
            '''
            result = subprocess.run(
                ["osascript", "-e", script],
                capture_output=True, text=True, timeout=5,
            )
            return result.returncode == 0
        return _reload

from __future__ import annotations

import time
import subprocess
import os
from .base import BaseSkill, Intent
from qingagent.core import actions, vision, window

class MinesweeperSkill(BaseSkill):
    app_name = "Minesweeper"
    app_aliases = ["扫雷", "玩扫雷", "扫雷游戏"]
    app_context = "浏览器中的扫雷网页游戏界面"

    def register_intents(self):
        self.add_intent(Intent(
            name="play_minesweeper",
            description="启动扫雷游戏，Agent 将展现神乎其技的高维透视起手式，主动点击盘面上的安全起手靶心！",
            required_slots=[],
            examples=[
                "咱们来玩扫雷吧",
                "帮我打开扫雷",
                "你可以玩扫雷吗？",
                "启动扫雷游戏"
            ],
        ))

    def execute_play_minesweeper(self, slots: dict) -> dict:
        print("🎮 收到指示，Agent 正在为你部署游戏战场...")
        
        # 1. 计算游戏页面的绝对路径
        current_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.dirname(os.path.dirname(current_dir))
        game_html_path = os.path.join(project_root, "web", "agent-minesweeper", "index.html")
        
        if not os.path.exists(game_html_path):
            return {"success": False, "message": f"游戏组件缺失，未找到: {game_html_path}", "data": None}

        # 2. 调度浏览器全屏装载扫雷战场
        print("🌐 正在挂载浏览器并注入本地扫雷程序...")
        try:
            # -a "Google Chrome" 可以指定用 Chrome，保险起见用默认 open 即可
            subprocess.run(["open", game_html_path], check=True)
            time.sleep(2.0)  # 给浏览器加载和渲染时间
        except Exception as e:
            return {"success": False, "message": f"装载战场失败: {e}", "data": None}

        # 3. 执行天眼视觉识别：在屏幕上寻找那个高亮的 "🎯" 靶心
        print("👁️ Agent 启动微观视觉系统，扫描安全破阵靶心...")
        baseline_img = self.screenshot()
        if not baseline_img:
            return {"success": False, "message": "视觉总成故障，无法获取桌面帧", "data": None}

        # 告诉 VLM 我们要找什么
        vlm_prompt = "寻找扫雷盘面中央，那个呈现紫蓝色霓虹渐变特效，并且里面包含有 🎯 这个靶心图标的方块格子。请绝对精准地框出它。"
        
        target_pt = vision.find_element_with_retry(baseline_img, vlm_prompt)
        if not target_pt:
            return {
                "success": False, 
                "message": "未能定位到安全起手靶心，可能页面被遮挡，安全起见已终止操作。", 
                "data": None
            }

        x, y = target_pt["rx"], target_pt["ry"]
        print(f"🎯 锁定绝对安全起手点！坐标：({x}, {y})")

        # 4. 执行物理级破阵打击
        import pyautogui
        
        # 模拟真实人类的平滑移位，展现优雅的压迫感
        pyautogui.moveTo(x, y, duration=0.8, tween=pyautogui.easeInOutQuad)
        print("💥 引爆破阵！")
        pyautogui.click()
        
        # 为了炫酷，鼠标点完迅速撤走
        pyautogui.moveRel(0, 100, duration=0.2)
        
        # 截个最终战果图返回给用户（可选，让日志更酷）
        time.sleep(0.5)
        self.screenshot()

        return {
            "success": True,
            "message": "已为你启动扫雷并精准点亮第一发安全起手靶心！局面目前极度舒适，请享受清台！",
            "data": {"status": "AI_started"}
        }

    def screenshot(self) -> str | None:
        """从底座获取全屏截图"""
        import pyautogui
        from qingagent.core import vision
        screen_w, screen_h = pyautogui.size()
        return vision.capture_screenshot((0, 0, screen_w, screen_h))

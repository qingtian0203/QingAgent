from __future__ import annotations

"""
TaskMonitorSkill — 通用 AI 任务监控器 v2

职责：
1. 两阶段识别：先看发送按钮颜色（灰/蓝=空闲，红方块=执行中），
   仅当空闲时才读取回覆末尾 DONE/FAIL/REVIEW 标记
2. [DONE] → 检查额度 → 必要时切换模型 → 发送「继续」
3. [FAIL/REVIEW] → HITL 截图推送
4. 灰色按钮但无结果（空转） → 自动切模型，连续 3 次才上报
5. 结构化日志：控制台 + 本地文件同时输出（路径: ~/qingagent_monitor.log）
6. 额度耗尽 → 每 30 分钟检查一次

可用 Intent：
- "查一下AG额度"         → check_quota
- "切换到Gemini模型"      → switch_model
- "读取AG当前状态"        → read_ag_status
- "让AG继续"              → click_continue
- "开始监控AG，自动续跑"  → watch_and_continue
"""

import time
import json
import re
import os
import datetime
import pyautogui

from .base import BaseSkill, Intent
from qingagent.core import actions, vision, window


# ── 常量配置 ──────────────────────────────────────
QUOTA_LOW_THRESHOLD  = 20          # 低于此额度触发切换
QUOTA_WAIT_INTERVAL  = 30 * 60    # 两端额度均不足时等待间隔（秒）
CHECK_INTERVAL       = 180         # 正常轮询间隔 3 分钟（秒）
MAX_THINKING_CYCLES  = 20          # 最大 THINKING 轮次 20×3min = 1h
MAX_IDLE_ERRORS      = 3           # 灰色空转连续次数超过此值才上报截图

# ── 日志文件路径 ──────────────────────────────────
_LOG_PATH = os.path.expanduser("~/qingagent_monitor.log")


# ──────────────────────────────────────────────────
#  日志工具
# ──────────────────────────────────────────────────

def _log(msg: str, *, tag: str = "INFO"):
    """结构化日志：控制台打印 + 追加写入本地文件"""
    ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] [{tag}] {msg}"
    print(line)
    try:
        with open(_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception as e:
        print(f"⚠️ 日志写入失败：{e}")


def _log_cycle(*, cycle: int, btn_state: str, ag_status: str,
               group1: int | None, group3: int | None, model: str, detail: str = ""):
    """每轮监控的汇总日志行（一行搞定）"""
    quota_str = (
        f"G1={group1}% G3={group3}%"
        if group1 is not None else "额度=未读取"
    )
    _log(
        f"[第{cycle}轮] 按钮={btn_state} | 回答={ag_status} | {quota_str} | 模型={model}"
        + (f" | {detail[:60]}" if detail else ""),
        tag="CYCLE",
    )


# ──────────────────────────────────────────────────
#  Skill 主体
# ──────────────────────────────────────────────────

class TaskMonitorSkill(BaseSkill):
    app_name    = "任务监控"
    app_aliases = [
        "任务监控", "AG监控", "自动续跑", "monitor",
        "监控", "AG续跑", "看守", "task monitor",
    ]
    app_context = "Antigravity AI 编码助手界面，包含左侧代码区和右侧 AI 对话面板"

    def register_intents(self):
        # ── 1. 查询额度 ──
        self.add_intent(Intent(
            name="check_quota",
            description="查询 Antigravity 底部状态栏的 Group1(Gemini) 和 Group3(Claude) 额度百分比",
            required_slots=[],
            examples=[
                "查一下AG额度还有多少", "看看Group1和Group3的余额",
                "检查一下模型额度", "AG的额度还剩多少", "现在还有多少额度",
            ],
        ))

        # ── 2. 切换模型 ──
        self.add_intent(Intent(
            name="switch_model",
            description="切换 Antigravity 当前使用的 AI 模型，支持 gemini(Group1) 或 claude(Group3)",
            required_slots=["target"],
            examples=[
                "切换到Gemini模型", "换成Claude Sonnet", "把AG换成Gemini",
                "切换到group1的模型", "切换到group3的Claude", "AG换成gemini",
            ],
        ))

        # ── 3. 读取 AG 状态 ──
        self.add_intent(Intent(
            name="read_ag_status",
            description="截图读取 Antigravity 对话面板中最新回覆末尾的状态标记：DONE/FAIL/REVIEW/THINKING",
            required_slots=[],
            examples=[
                "看看AG回复完了没有", "检查AG当前状态",
                "AG有没有输出完成标记", "读取AG的回复状态", "AG做完了吗",
            ],
        ))

        # ── 4. 发送继续 ──
        self.add_intent(Intent(
            name="click_continue",
            description="在 Antigravity 对话输入框输入「继续」并发送，让 AI 执行下一步",
            required_slots=[],
            optional_slots=["message"],
            examples=["让AG继续", "发送继续给AG", "叫AG继续执行", "AG继续"],
        ))

        # ── 5. 主监控循环 ──
        self.add_intent(Intent(
            name="watch_and_continue",
            description=(
                "持续监控 Antigravity 任务执行状态（两阶段：按钮颜色→内容状态）。"
                "DONE 后自动检查额度并发送「继续」；FAIL/REVIEW 截图推送 HITL；"
                "灰色空转自动切模型，3次失败才上报。"
            ),
            required_slots=[],
            optional_slots=["notify_contact"],
            examples=[
                "开始监控AG，自动续跑", "帮我盯着AG，完成了就继续",
                "自动续跑模式启动", "开始看守AG任务，有问题叫我",
                "监控AG任务执行", "AG自动模式",
                "开始监控ag跑任务", "监控ag跑任务",
                "帮我看着ag", "让ag自动跑",
                "开始AG自动监控", "AG挂机跑",
                "盯着AG自动续跑", "监控AG别让它停",
            ],
        ))

    # ──────────────────────────────────────────────
    #  窗口激活（复用 Antigravity 进程别名）
    # ──────────────────────────────────────────────

    def activate(self) -> bool:
        result = window.activate_and_find(["Antigravity", "Cursor", "cursor"])
        if not result:
            time.sleep(2.0)
            result = window.find_window(["Cursor", "Antigravity", "cursor"])
        if result:
            time.sleep(0.6)
            self._window_rect = result["rect"]
            return True
        _log("❌ 未找到 Antigravity 窗口，请确认 Cursor 已启动", tag="ERROR")
        return False

    # ──────────────────────────────────────────────
    #  Intent 1: 查询额度
    # ──────────────────────────────────────────────

    def execute_check_quota(self, slots: dict) -> dict:
        """裁剪底部状态栏，纯文字识别 Group1/Group3 百分比"""
        if not self.activate():
            return {"success": False, "message": "无法激活 Antigravity 窗口", "data": None}

        screen_w, screen_h = pyautogui.size()
        status_bar_rect = (0, screen_h - 40, screen_w, 40)
        status_img = vision.capture_screenshot(status_bar_rect)
        if not status_img:
            return {"success": False, "message": "无法截取状态栏", "data": None}

        raw = vision.read_screen_content(
            status_img,
            question=(
                "找到文字 'Group 1:' 后面跟着的百分比数字，以及 'Group 3:' 后面跟着的百分比数字。"
                "只返回纯 JSON，格式：{\"group1\": 整数, \"group3\": 整数}，不要其他文字。"
            ),
            context="软件底部状态栏，格式类似：Group 1: 80% | Group 3: 15%",
        )

        group1, group3 = self._parse_quota(raw)
        if group1 is None or group3 is None:
            return {"success": False, "message": f"无法解析额度：{raw}", "data": None}

        msg = f"✅ Group1(Gemini): {group1}% | Group3(Claude): {group3}%"
        return {"success": True, "message": msg, "data": {"group1": group1, "group3": group3}}

    def _parse_quota(self, text: str):
        try:
            data = json.loads(text)
            return int(data.get("group1", 0)), int(data.get("group3", 0))
        except Exception:
            pass
        try:
            m1 = re.search(r"[Gg]roup\s*1\D{0,5}?(\d+)", text)
            m3 = re.search(r"[Gg]roup\s*3\D{0,5}?(\d+)", text)
            g1 = int(m1.group(1)) if m1 else None
            g3 = int(m3.group(1)) if m3 else None
            return g1, g3
        except Exception:
            return None, None

    # ──────────────────────────────────────────────
    #  Intent 2: 切换模型
    # ──────────────────────────────────────────────

    def execute_switch_model(self, slots: dict) -> dict:
        target = slots.get("target", "").lower()
        if "gemini" in target or "group1" in target:
            target_name = "Gemini 3.1 Pro (High)"
            target_hint = "浮层菜单中完整文字为 'Gemini 3.1 Pro (High)' 的菜单行，括号内是 High 而不是 Low"
        elif "claude" in target or "sonnet" in target or "group3" in target:
            target_name = "Claude Sonnet 4.6 (Thinking)"
            target_hint = "浮层菜单中完整文字为 'Claude Sonnet 4.6 (Thinking)' 的菜单行，是 Sonnet 而不是 Opus"
        else:
            return {"success": False, "message": f"不认识的目标模型：{target}", "data": None}

        if not self.activate():
            return {"success": False, "message": "无法激活 Antigravity 窗口", "data": None}

        img = self.screenshot()
        if not img:
            return {"success": False, "message": "截图失败", "data": None}

        btn_coords = vision.find_element(
            img,
            target="Antigravity 对话面板底部工具栏中，'Planning' 右边且 'MCP Error' 左边的当前模型名称按钮",
            context="AI 对话面板底部状态栏",
        )
        if not btn_coords:
            return {"success": False, "message": "找不到模型切换按钮", "data": None}

        actions.click_at_normalized(getattr(self, "_last_screenshot_rect", self._window_rect), btn_coords)
        time.sleep(0.7)

        img2 = self.screenshot()
        if not img2:
            return {"success": False, "message": "下拉菜单截图失败", "data": None}

        menu_coords = vision.find_element(img2, target=target_hint, context="模型选择浮层菜单")
        if not menu_coords:
            return {"success": False, "message": f"菜单中找不到：{target_name}", "data": None}

        actions.click_at_normalized(getattr(self, "_last_screenshot_rect", self._window_rect), menu_coords)
        time.sleep(0.5)
        msg = f"🔄 已切换到 {target_name}"
        _log(msg, tag="SWITCH")
        return {"success": True, "message": msg, "data": {"model": target_name}}

    # ──────────────────────────────────────────────
    #  Intent 3: 读取 AG 回覆状态
    # ──────────────────────────────────────────────

    def execute_read_ag_status(self, slots: dict) -> dict:
        if not self.activate():
            return {"success": False, "message": "无法激活 Antigravity 窗口", "data": None}

        img = self.screenshot()
        if not img:
            return {"success": False, "message": "截图失败", "data": None}

        raw = vision.read_screen_content(
            img,
            question=(
                "在右侧 AI 对话面板中，找到最新一条 AI 回覆的最后几行。"
                "判断是否出现：[DONE]（完成）、[FAIL]（失败）、[REVIEW]（要审查）。"
                "没有以上标记但 AI 还在输出则为 THINKING，没有输出且也无标记为 UNKNOWN。"
                "只返回纯 JSON：{\"status\": \"DONE\"/\"FAIL\"/\"REVIEW\"/\"THINKING\"/\"UNKNOWN\", "
                "\"detail\": \"最后2-3行文字摘要\"}"
            ),
            context="Antigravity AI 编码助手对话面板（右侧面板），AI 完成后最后一行输出 [DONE]/[FAIL]/[REVIEW]",
        )

        status, detail = self._parse_status(raw)
        return {"success": True, "message": f"AG状态：{status}", "data": {"status": status, "detail": detail}}

    def _parse_status(self, text: str):
        try:
            data = json.loads(text)
            return data.get("status", "UNKNOWN").upper(), data.get("detail", "")
        except Exception:
            pass
        upper = text.upper()
        if "[DONE]" in upper:   return "DONE", text
        if "[FAIL]" in upper:   return "FAIL", text
        if "[REVIEW]" in upper: return "REVIEW", text
        if any(kw in upper for kw in ["THINKING", "思考中", "..."]):
            return "THINKING", text
        return "UNKNOWN", text[:200]

    # ──────────────────────────────────────────────
    #  Intent 3.5: 识别发送按钮颜色状态（两阶段前置检查）
    # ──────────────────────────────────────────────

    def _read_send_button_state(self) -> str:
        """
        读取右下角发送按钮颜色，返回：
          'RED'   — 灰色底 + 内部红色实心正方形（AI 正在执行/可停止）
          'BLUE'  — 蓝色圆形底 + 白色向右箭头（输入框有内容，可发送）
          'GRAY'  — 灰色圆形底 + 白色向右箭头（输入框为空，不可点击）
          'UNKNOWN' — 无法识别
        """
        img = self.screenshot()
        if not img:
            return "UNKNOWN"

        raw = vision.read_screen_content(
            img,
            question=(
                "请仔细观察界面右下角（输入框最右侧）的那个小圆形按钮，判断它的当前状态。\n\n"
                "该按钮只有以下三种状态，请严格按照视觉特征区分：\n\n"
                "状态1 → 返回 RED：\n"
                "  - 按钮整体背景为【中性灰色】圆形\n"
                "  - 按钮内部有一个【鲜红色的实心正方形/方块】图标（停止图标）\n"
                "  - 代表 AI 正在执行任务，点击可终止\n\n"
                "状态2 → 返回 BLUE：\n"
                "  - 按钮整体背景为【鲜艳蓝色/深蓝色】圆形（颜色饱和、醒目）\n"
                "  - 按钮内部有一个【白色的向右方向箭头】图标（发送图标）\n"
                "  - 代表输入框内有文字内容，可以发送\n\n"
                "状态3 → 返回 GRAY：\n"
                "  - 按钮整体背景为【浅灰色】圆形（暗淡、不鲜艳）\n"
                "  - 按钮内部有一个【白色的向右方向箭头】图标（与状态2相同图标）\n"
                "  - 代表输入框为空，按钮不可点击\n\n"
                "关键区分点：\n"
                "  - BLUE 和 GRAY 的图标相同（都是白色右箭头），区别在底色：蓝色=BLUE，灰色=GRAY\n"
                "  - RED 的底色也是灰色，但内部图标是红色方块而非箭头，这是与 GRAY 的唯一区别\n\n"
                "只返回纯 JSON，格式：{\"button\": \"RED\"} 或 {\"button\": \"BLUE\"} 或 {\"button\": \"GRAY\"} 或 {\"button\": \"UNKNOWN\"}\n"
                "不要输出任何其他文字。"
            ),
            context=(
                "这是 Antigravity（基于 Cursor 的 AI 编程助手）对话面板右下角的发送/停止按钮。"
                "该按钮紧贴输入框右侧，是一个小圆形图标。"
                "三种状态：灰底+红方块(RED=执行中)、蓝底+白箭头(BLUE=待发送)、灰底+白箭头(GRAY=空闲)"
            ),
        )

        try:
            data = json.loads(raw)
            state = data.get("button", "UNKNOWN").upper()
            if state in ("RED", "BLUE", "GRAY"):
                return state
        except Exception:
            pass

        # 正则兜底（防止模型在 JSON 外夹杂文字）
        upper = raw.upper()
        if "\"RED\"" in upper or "RED" in upper and "SQUARE" in upper:
            return "RED"
        if "\"BLUE\"" in upper or ("BLUE" in upper and "ARROW" in upper):
            return "BLUE"
        if "\"GRAY\"" in upper or "GRAY" in upper:
            return "GRAY"
        return "UNKNOWN"

    # ──────────────────────────────────────────────
    #  Intent 4: 发送「继续」
    # ──────────────────────────────────────────────

    def execute_click_continue(self, slots: dict) -> dict:
        message = slots.get("message", "继续")
        if not self.activate():
            return {"success": False, "message": "无法激活 Antigravity 窗口", "data": None}

        _log(f"⌨️ 向 AG 发送：{message}", tag="SEND")
        actions.hotkey("command", "1", delay=0.2)
        actions.hotkey("command", "l", delay=0.8)
        actions.type_text(message)
        time.sleep(0.2)
        actions.press_key("enter")

        return {"success": True, "message": f"✅ 已向 AG 发送：{message}", "data": {"message": message}}

    # ──────────────────────────────────────────────
    #  Intent 5: 主监控循环（强化版）
    # ──────────────────────────────────────────────

    def execute_watch_and_continue(self, slots: dict) -> dict:
        """
        主循环（两阶段 + 日志 + 静默故障自愈）：

        阶段1：识别发送按钮颜色
          RED  → AI 正在执行，直接等待下一轮
          GRAY → AI 空闲，进入阶段2
          BLUE → 理论上不应出现（无人打字）；进入阶段2

        阶段2（仅当按钮 GRAY/BLUE）：读取回覆状态
          THINKING → 等下一轮
          DONE     → 检查额度 → 切换模型（若需）→ 发送继续
          FAIL/REVIEW → 推送 HITL 截图
          UNKNOWN  → 计入「灰色空转」；连续 3 次切模型+发继续+上报截图
        """
        _log("🚀 [监控模式] watch_and_continue 启动，日志路径：" + _LOG_PATH, tag="START")
        _log(f"⚙️ 配置：轮询间隔={CHECK_INTERVAL}s，额度阈值={QUOTA_LOW_THRESHOLD}%，最大空转={MAX_IDLE_ERRORS}次", tag="CONFIG")

        cycle          = 0
        thinking_cycles = 0
        idle_error_count = 0  # 连续灰色且无结果计数

        while True:
            self.check_cancel()
            cycle += 1

            # ── 阶段 1：识别发送按钮颜色 ──────────────
            if not self.activate():
                _log("❌ 激活窗口失败，跳过本轮", tag="WARN")
                time.sleep(CHECK_INTERVAL)
                continue

            btn_state = self._read_send_button_state()

            # 正在执行（红色方块）→ 直接等待，无需读内容
            if btn_state == "RED":
                thinking_cycles += 1
                if thinking_cycles > MAX_THINKING_CYCLES:
                    msg = f"⏰ 超过 {MAX_THINKING_CYCLES * CHECK_INTERVAL // 60} 分钟仍在执行（红色按钮），退出监控"
                    _log(msg, tag="TIMEOUT")
                    return {"success": False, "message": msg, "data": {"status": "TIMEOUT"}}

                _log_cycle(cycle=cycle, btn_state="RED(执行中)", ag_status="—",
                           group1=None, group3=None, model="—",
                           detail=f"跳过内容读取，等待{CHECK_INTERVAL}s")
                time.sleep(CHECK_INTERVAL)
                continue

            # ── 阶段 2：按钮灰色/蓝色 → 读取回覆状态 ──
            thinking_cycles = 0  # 不再红色，重置计数

            status_result = self.execute_read_ag_status({})
            ag_status = "ERROR"
            detail    = ""
            if status_result["success"]:
                ag_status = status_result["data"]["status"]
                detail    = status_result["data"].get("detail", "")

            # 读取额度（每轮都读，用于日志）
            g1, g3   = None, None
            cur_model = "—"
            quota_result = self.execute_check_quota({})
            if quota_result["success"]:
                g1 = quota_result["data"]["group1"]
                g3 = quota_result["data"]["group3"]
                cur_model = self._read_current_model_name()

            _log_cycle(cycle=cycle, btn_state=f"GRAY/BLUE({btn_state})", ag_status=ag_status,
                       group1=g1, group3=g3, model=cur_model, detail=detail)

            # ── THINKING：继续等待 ──
            if ag_status == "THINKING":
                _log(f"⏳ AG 仍在思考，{CHECK_INTERVAL}s 后重试", tag="WAIT")
                time.sleep(CHECK_INTERVAL)
                continue

            # ── FAIL / REVIEW：人工介入 ──
            if ag_status in ("FAIL", "REVIEW"):
                _log(f"🆘 [{ag_status}] 需要人工介入，推送 HITL 截图", tag="HITL")
                screenshot = self.screenshot()
                try:
                    from qingagent.server import app as server_app
                    if screenshot:
                        server_app.request_hitl_confirm(screenshot)
                except Exception as e:
                    _log(f"HITL 推送失败：{e}", tag="ERROR")
                return {
                    "success": True,
                    "message": f"⚠️ AG 出现 [{ag_status}]，已推送截图，请在 Web UI 处理后重新启动监控",
                    "data": {"status": ag_status, "action": "HITL_WAIT"},
                }

            # ── DONE：正常完成，发送继续 ──
            if ag_status == "DONE":
                idle_error_count = 0  # 成功完成，重置空转计数
                _log("✅ AG 完成本步骤，检查额度并发送继续", tag="DONE")

                if g1 is not None and g3 is not None:
                    is_claude  = "claude" in cur_model.lower() or "sonnet" in cur_model.lower()
                    is_gemini  = "gemini" in cur_model.lower()

                    if is_claude and g3 < QUOTA_LOW_THRESHOLD:
                        if g1 >= QUOTA_LOW_THRESHOLD:
                            _log(f"⚡ Claude 额度不足({g3}%)，切换 Gemini({g1}%)", tag="SWITCH")
                            self.execute_switch_model({"target": "gemini"})
                            time.sleep(0.5)
                        else:
                            self._wait_for_quota_recovery()
                            continue
                    elif is_gemini and g1 < QUOTA_LOW_THRESHOLD:
                        if g3 >= QUOTA_LOW_THRESHOLD:
                            _log(f"⚡ Gemini 额度不足({g1}%)，切换 Claude({g3}%)", tag="SWITCH")
                            self.execute_switch_model({"target": "claude"})
                            time.sleep(0.5)
                        else:
                            self._wait_for_quota_recovery()
                            continue

                self.execute_click_continue({"message": "继续"})
                _log(f"📤 已发送「继续」，{CHECK_INTERVAL}s 后下一轮", tag="SEND")
                time.sleep(CHECK_INTERVAL)
                continue

            # ── UNKNOWN / ERROR：灰色空转处理 ──
            idle_error_count += 1
            _log(
                f"❓ 按钮空闲但无有效状态（UNKNOWN/ERROR），"
                f"连续第 {idle_error_count}/{MAX_IDLE_ERRORS} 次",
                tag="IDLE",
            )

            # 尝试切换模型 + 发继续（自愈）
            if g1 is not None and g3 is not None:
                is_claude  = "claude" in cur_model.lower() or "sonnet" in cur_model.lower()
                is_gemini  = "gemini" in cur_model.lower()
                switched   = False

                if is_claude and g3 < QUOTA_LOW_THRESHOLD and g1 >= QUOTA_LOW_THRESHOLD:
                    _log(f"🔄 空转自愈：Claude 额度低 ({g3}%)，切换 Gemini", tag="IDLE_HEAL")
                    self.execute_switch_model({"target": "gemini"})
                    switched = True
                elif is_gemini and g1 < QUOTA_LOW_THRESHOLD and g3 >= QUOTA_LOW_THRESHOLD:
                    _log(f"🔄 空转自愈：Gemini 额度低 ({g1}%)，切换 Claude", tag="IDLE_HEAL")
                    self.execute_switch_model({"target": "claude"})
                    switched = True

                if switched:
                    time.sleep(0.5)

            _log("🔁 空转自愈：发送「继续」唤醒任务", tag="IDLE_HEAL")
            self.execute_click_continue({"message": "继续"})

            # 连续 MAX_IDLE_ERRORS 次 → 上报截图 + 退出
            if idle_error_count >= MAX_IDLE_ERRORS:
                _log(f"🆘 连续 {MAX_IDLE_ERRORS} 次灰色空转，上报截图并退出监控", tag="ERROR")
                screenshot = self.screenshot()
                try:
                    from qingagent.server import app as server_app
                    if screenshot:
                        server_app.request_hitl_confirm(screenshot)
                except Exception as e:
                    _log(f"HITL 推送失败：{e}", tag="ERROR")
                return {
                    "success": False,
                    "message": f"🆘 连续 {MAX_IDLE_ERRORS} 次灰色空转（可能是额度耗尽或网络异常），已推送截图",
                    "data": {"status": "IDLE_ERROR", "count": idle_error_count},
                }

            _log(f"⏳ 等待 {CHECK_INTERVAL}s 后重试", tag="IDLE")
            time.sleep(CHECK_INTERVAL)

    # ──────────────────────────────────────────────
    #  内部辅助
    # ──────────────────────────────────────────────

    def _read_current_model_name(self) -> str:
        img = self.screenshot()
        if not img:
            return ""
        name = vision.read_screen_content(
            img,
            question=(
                "在 Antigravity 对话面板底部工具栏中，"
                "'Planning' 右边、'MCP Error' 左边显示的当前模型名称是什么？"
                "只返回模型名称文字，不要其他内容。"
            ),
            context="AI 对话面板底部状态栏",
        )
        return name.strip()

    def _wait_for_quota_recovery(self):
        """两端额度均不足，每 30 分钟轮询一次直到恢复"""
        _log(f"😴 两端额度均不足，进入等待模式（{QUOTA_WAIT_INTERVAL // 60} 分钟检查一次）", tag="QUOTA_WAIT")
        while True:
            self.check_cancel()
            time.sleep(QUOTA_WAIT_INTERVAL)
            result = self.execute_check_quota({})
            if result["success"]:
                g1 = result["data"]["group1"]
                g3 = result["data"]["group3"]
                _log(f"📊 额度检查：Group1={g1}% | Group3={g3}%", tag="QUOTA_WAIT")
                if g1 >= QUOTA_LOW_THRESHOLD or g3 >= QUOTA_LOW_THRESHOLD:
                    _log("✅ 额度已恢复，继续任务！", tag="QUOTA_WAIT")
                    return
            _log("😴 额度仍不足，继续等待...", tag="QUOTA_WAIT")

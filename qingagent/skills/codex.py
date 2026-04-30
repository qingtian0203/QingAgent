from __future__ import annotations

"""
Codex Skill — Codex 桌面端消息注入

核心场景：
1. send_prompt - 在 Codex 当前会话底部输入框发送一条消息

定位策略：
- 主路径：macOS 无障碍树命中真实 AXTextArea 输入控件
- 二级兜底：AI 视觉按“要求后续变更”等 UI 语义识别输入框
- 末级兜底：按“左侧栏 + 主内容区”布局计算文本区坐标
- 发送：输入完成后按 Enter，避免识别右下角发送 / 停止按钮状态
"""
import time as _time

from .base import BaseSkill, Intent
from qingagent.core import actions


class CodexSkill(BaseSkill):
    app_name = "Codex"
    ui_label = "Codex 控制"
    app_aliases = ["Codex", "codex", "代码助手"]
    app_context = "Codex 桌面端聊天窗口截图"
    cold_start_wait = 5.0

    # Codex 桌面端左侧通常有项目/会话栏。输入框在右侧主内容区底部，
    # 不能按整个窗口的左上角直接取比例，否则会点到侧栏或聊天内容外侧。
    MAIN_PANE_LEFT_RATIO = 0.25
    MAIN_PANE_MIN_LEFT = 220
    MAIN_PANE_MAX_LEFT = 270
    INPUT_TEXT_LEFT_PADDING = 55
    INPUT_TEXT_BOTTOM_OFFSET = 100

    def register_intents(self):
        self.add_intent(Intent(
            name="send_prompt",
            description="在 Codex 桌面端当前会话中发送一条消息或代码指令",
            required_slots=["prompt"],
            examples=[
                "给Codex发消息说 测试一下",
                "给codex发个消息说 帮我评审这个方案",
                "让Codex回复一下 hello",
                "发给Codex：请检查 QingOA 的 OKR 设计",
                "给代码助手发消息说 做一个方案评审",
            ],
        ))
        self.add_intent(Intent(
            name="focus_input",
            description="聚焦 Codex 桌面端当前会话底部输入框，用于验证是否能稳定输入",
            required_slots=[],
            examples=[
                "聚焦Codex输入框",
                "测试Codex输入框能不能定位",
                "把焦点放到Codex输入框",
            ],
        ))

    def execute_send_prompt(self, slots: dict) -> dict:
        prompt = slots["prompt"]

        if not self.activate():
            return {"success": False, "message": "无法激活 Codex", "data": None}

        if not self._focus_input():
            return {"success": False, "message": "找不到 Codex 输入框", "data": None}

        # 覆盖当前草稿，避免把新消息拼到旧输入后面。
        actions.hotkey("command", "a", delay=0.1)
        actions.type_text(prompt)
        _time.sleep(0.2)
        actions.press_key("enter", delay=0.4)

        return {
            "success": True,
            "message": f"已发送指令到 Codex：{prompt[:50]}...",
            "data": None,
        }

    def execute_focus_input(self, slots: dict) -> dict:
        if not self.activate():
            return {"success": False, "message": "无法激活 Codex", "data": None}

        focused = self._focus_input()
        return {
            "success": focused,
            "message": "已聚焦 Codex 输入框" if focused else "找不到 Codex 输入框",
            "data": None,
        }

    def _focus_input(self) -> bool:
        """
        聚焦 Codex 输入框。

        当前 Codex app 包内没有发现类似 Antigravity Cmd+L 的
        “聚焦当前会话 composer”快捷键，所以这里不伪造快捷键。

        多段式定位：
        1. macOS 无障碍树命中真实 AXTextArea，不依赖分辨率 / 像素颜色
        2. AI 视觉用底部输入框 hint 文案和周边控件做语义定位
        3. 坐标兜底，仅在前两者失败时使用
        """
        if self._focus_input_by_accessibility_layout():
            return True
        if self._focus_input_by_vision():
            return True
        return self._focus_input_by_main_pane_layout()

    def _focus_input_by_accessibility_layout(self) -> bool:
        """
        优先使用 macOS Accessibility 的几何信息。

        这条路不依赖截图，所以能避开多显示器负坐标下 screencapture -R
        截不到图的问题。能拿到主内容区时，点击主内容区底部的文本编辑区。
        """
        if not self._window_rect:
            return False

        context = self._get_accessibility_context()
        if not context:
            return False
        AS, app = context

        try:
            err, windows = AS.AXUIElementCopyAttributeValue(app, "AXWindows", None)
            if err != 0 or not windows:
                return False

            target_window = None
            for win in list(windows):
                rect = self._ax_rect(AS, win)
                if rect and self._rects_close(self._window_rect, rect):
                    target_window = win
                    break
            if target_window is None:
                target_window = list(windows)[0]

            main_rect = self._find_ax_main_pane_rect(AS, target_window)
            if not main_rect:
                return False

            print(
                "🧭 [Codex无障碍定位] main="
                f"{tuple(round(v) for v in main_rect)}"
            )
            return self.click_text_input_by_accessibility(
                search_rect=main_rect,
                placeholder_keywords=("要求后续变更",),
                label="Codex输入框",
            )
        except Exception as e:
            print(f"⚠️ [Codex无障碍定位] 失败：{e}")
            return False

    def _focus_input_by_main_pane_layout(self) -> bool:
        if not self._window_rect:
            return False

        main_rect = self._estimate_main_pane_rect()
        click_x, click_y = self._composer_point_from_main_rect(main_rect)
        print(
            "🧭 [Codex主内容区定位] main="
            f"{tuple(round(v) for v in main_rect)}，点击输入区 ({click_x:.0f}, {click_y:.0f})"
        )
        actions.click_at_physical(click_x, click_y, delay=0.2)
        return True

    def _focus_input_by_vision(self) -> bool:
        print("⚠️ Codex AX 语义定位失败，切换 AI 视觉识别...")
        return self.find_and_click(
            "请定位 Codex 当前会话窗口最底部的消息输入框文本编辑区。"
            "这个输入框是一个横向很长的白色大圆角矩形，内部左上角通常有浅灰色提示文字“要求后续变更”。"
            "它位于最后一条回复和点赞/点踩/分支图标的下方，也可能位于“1个文件已更改”灰色卡片的下方。"
            "输入框底部工具栏有加号、橙色“完全访问权限”、模型选择“5.5 超高”、麦克风图标、右下角黑色圆形发送箭头。"
            "请点击输入框内部左上方的文本编辑区域，也就是“要求后续变更”提示文字附近。"
            "不要点击右下角黑色发送按钮，不要点击底部工具栏，不要点击上方回复正文或文件变更卡片。"
        )

    def _estimate_main_pane_rect(self) -> tuple[float, float, float, float]:
        x, y, w, h = self._window_rect
        if w >= 760:
            sidebar_w = max(
                self.MAIN_PANE_MIN_LEFT,
                min(self.MAIN_PANE_MAX_LEFT, w * self.MAIN_PANE_LEFT_RATIO),
            )
        else:
            sidebar_w = 0

        main_x = x + sidebar_w
        return (main_x, y, max(1, w - sidebar_w), h)

    def _composer_point_from_main_rect(
        self,
        main_rect: tuple[float, float, float, float],
    ) -> tuple[float, float]:
        x, y, w, h = main_rect
        bottom_offset = min(
            self.INPUT_TEXT_BOTTOM_OFFSET,
            max(100, h * 0.16),
        )
        return (
            x + min(self.INPUT_TEXT_LEFT_PADDING, max(40, w * 0.12)),
            y + h - bottom_offset,
        )

    def _find_ax_main_pane_rect(self, AS, window_element) -> tuple[float, float, float, float] | None:
        win_rect = self._ax_rect(AS, window_element) or self._window_rect
        win_x, win_y, win_w, win_h = win_rect
        best = None

        def children(element):
            result = []
            seen = set()
            for attr in ("AXChildren", "AXVisibleChildren", "AXContents"):
                vals = self._ax_attr(AS, element, attr)
                if not vals:
                    continue
                for child in list(vals):
                    marker = id(child)
                    if marker not in seen:
                        seen.add(marker)
                        result.append(child)
            return result

        def walk(element, depth: int = 0):
            nonlocal best
            if depth > 12:
                return

            role = str(self._ax_attr(AS, element, "AXRole") or "")
            rect = self._ax_rect(AS, element)
            if rect and role in {"AXGroup", "AXWebArea", "AXScrollArea"}:
                x, y, w, h = rect
                is_not_whole_window = w < win_w * 0.95
                is_right_main_area = x >= win_x + min(160, win_w * 0.2)
                is_large_enough = w >= win_w * 0.45 and h >= win_h * 0.70
                is_aligned = abs(y - win_y) <= 80 or y <= win_y + win_h * 0.15
                if is_not_whole_window and is_right_main_area and is_large_enough and is_aligned:
                    score = w * h + x * 2
                    if best is None or score > best[0]:
                        best = (score, rect)

            for child in children(element)[:120]:
                walk(child, depth + 1)

        walk(window_element)
        return best[1] if best else None

from __future__ import annotations

"""
Skill 基类 — 所有应用 Skill 的模板

每个应用的 Skill 需要：
1. 声明自己支持哪些意图（intents）
2. 实现每个意图对应的执行流程
3. 提供应用的基本信息（名称、别名、上下文描述）
"""
from dataclasses import dataclass, field
from qingagent.core import window, vision, actions, verify


@dataclass
class Intent:
    """
    一个意图定义。

    属性:
        name: 意图标识符，如 "send_message"
        description: 自然语言描述，给 AI Planner 看的
        ui_label: 用户可读的中文短标签，如 "发送消息/图片"
        required_slots: 必须提取的参数，如 ["contact_name", "message"]
        optional_slots: 可选参数
        examples: 示例用语，帮助 AI 匹配意图
        output_fields: 此意图执行后会产出的数据字段，如 ["screenshot_path"]
    """
    name: str
    description: str
    ui_label: str = ""                          # 用户可读的中文短标签
    required_slots: list[str] = field(default_factory=list)
    optional_slots: list[str] = field(default_factory=list)
    examples: list[str] = field(default_factory=list)
    output_fields: list[str] = field(default_factory=list)  # 产物字段


class UserCancelException(Exception):
    """用户强行终止任务引发的异常"""
    pass


class BaseSkill:
    """
    应用 Skill 基类 — 所有具体应用 Skill 的父类。

    子类需要实现：
    - app_name: 应用显示名称
    - ui_label: 用户可读的中文 Skill 标签（默认等于 app_name）
    - app_aliases: 进程名别名列表
    - app_context: AI 视觉识别时的上下文描述
    - intents: 支持的意图列表
    - execute_xxx(): 每个意图对应的执行方法
    """

    # --- 子类必须覆写 ---
    app_name: str = "未知应用"
    ui_label: str = ""          # 用户可读中文标签，空则自动使用 app_name
    app_aliases: list[str] = []
    app_context: str = "软件截图"

    def __init__(self):
        self._intents: dict[str, Intent] = {}
        self._window_rect = None
        self._verifier = None
        self._cancel_check = None
        self.register_intents()

    def check_cancel(self):
        """探测是否被用户强行终止，如果是，瞬间抛异常中止全链路。"""
        if self._cancel_check and self._cancel_check():
            raise UserCancelException("操作已被用户强行终止")

    def register_intents(self):
        """子类在这里注册自己支持的意图"""
        pass

    def add_intent(self, intent: Intent):
        """注册一个意图"""
        self._intents[intent.name] = intent

    def get_intents(self) -> dict[str, Intent]:
        """获取所有支持的意图"""
        return self._intents

    def get_intent_descriptions(self) -> str:
        """生成意图描述文本（给 Planner 用）"""
        # 标题包含别名，让 AI 知道简写对应关系
        aliases = [a for a in self.app_aliases if a != self.app_name]
        alias_text = f"（也叫：{'/'.join(aliases)}）" if aliases else ""
        lines = [f"# {self.app_name}{alias_text} 支持的操作：\n"]
        for name, intent in self._intents.items():
            lines.append(f"## {name}: {intent.description}")
            if intent.required_slots:
                lines.append(f"   必需参数: {', '.join(intent.required_slots)}")
            if intent.optional_slots:
                lines.append(f"   可选参数: {', '.join(intent.optional_slots)}")
            if intent.examples:
                lines.append(f"   示例: {' / '.join(intent.examples)}")
            lines.append("")
        return "\n".join(lines)

    # 冷启动默认等待时长（子类可以覆盖）
    cold_start_wait: float = 3.0

    def _is_running(self) -> bool:
        """检测应用是否已在运行（通过进程名匹配）"""
        import subprocess
        for alias in self.app_aliases:
            result = subprocess.run(
                ["pgrep", "-ix", alias],
                capture_output=True
            )
            if result.returncode == 0:
                return True
        return False

    def activate(self) -> bool:
        """激活应用并获取窗口（自动处理冷启动和台前调度唤醒的等待）"""
        import time as _time
        t0 = _time.time()

        # 检测是否冷启动
        is_cold = not self._is_running()
        if is_cold:
            print(f"🆕 {self.app_name} 未运行，冷启动中...")

        # 激活应用（只激活一次）
        window.activate_app(self.app_aliases[0])

        # 轮询等待窗口出现（用真实经过时间，防止 find_window 耗时导致计数失准）
        max_wait = self.cold_start_wait if is_cold else 8.0
        poll_interval = 0.5
        result = None
        start_poll = _time.time()
        first_miss = True

        while _time.time() - start_poll <= max_wait:
            self.check_cancel()  # 轮询时持续探测打断状态
            result = window.find_window(self.app_aliases, silent=True)  # 轮询时静默
            if result:
                break
            if first_miss:
                print(f"⏳ 等待 {self.app_name} 窗口出现（最多 {max_wait:.0f}s）...")
                first_miss = False
            _time.sleep(poll_interval)

        # 如果超时后还是没有，最后一次带日志输出查找一下
        if not result:
            result = window.find_window(self.app_aliases, silent=False)

        if result:
            self._window_rect = result["rect"]
            self._verifier = verify.StepVerifier(
                self._window_rect, context=self.app_context
            )
            print(f"✅ {self.app_name} 窗口就绪（等待了 {_time.time() - start_poll:.1f}s）：{self._window_rect}")
            print(f"⏱️ [激活应用] 耗时：{_time.time() - t0:.1f}s")
            # 预热截图，确保 _last_screenshot_rect 已被赋值（含 PAD 扩边），
            # 防止之后第一次 find_and_click 回退到无 PAD 的裸 _window_rect 导致偏移
            self.screenshot()
            return True
        else:
            print(f"❌ 等待 {max_wait}s 仍无法找到 {self.app_name} 窗口")
            return False

    def screenshot(self, save_path: str = None) -> str | None:
        """截取当前应用窗口（向四周外扩 200px 以捕获溢出的弹窗和菜单）"""
        if not self._window_rect:
            print("❌ 尚未定位窗口，请先调用 activate()")
            return None
            
        import pyautogui
        screen_w, screen_h = pyautogui.size()
        x, y, w, h = self._window_rect
        # ⚠️ 不加任何 PAD！精确截取窗口本身。
        # 原来 PAD=200 会把桌面、其他 App 图标、macOS 菜单栏都截进来，
        # AI 模型在大图里迷失方向，找到"日历相关词汇"的其他元素。
        # 弹窗/菜单出现在窗口外时，应通过 switch_to_popup() 切换到弹窗矩形来处理。
        nx, ny, nw, nh = x, y, w, h

        self._last_screenshot_rect = (int(nx), int(ny), int(nw), int(nh))
        return vision.capture_screenshot(self._last_screenshot_rect, save_path)

    def switch_to_popup(self) -> bool:
        """
        切换截图区域到弹窗窗口（同进程的较小窗口）。
        用于操作 CTkToplevel 等弹出对话框时提高 AI 视觉定位精度。
        调用前需先 activate() 主窗口，调用后截图和点击都以弹窗为基准。
        """
        from Quartz import (
            CGWindowListCopyWindowInfo,
            kCGWindowListOptionOnScreenOnly,
            kCGNullWindowID,
        )

        # 保存主窗口 rect（用于之后恢复）
        if not hasattr(self, '_main_window_rect') or self._main_window_rect is None:
            self._main_window_rect = self._window_rect

        window_list = CGWindowListCopyWindowInfo(
            kCGWindowListOptionOnScreenOnly, kCGNullWindowID
        )

        # 找同进程的所有窗口
        candidates = []
        for w in window_list:
            owner = w.get("kCGWindowOwnerName", "")
            if any(alias.lower() in owner.lower() for alias in self.app_aliases):
                bounds = w.get("kCGWindowBounds", {})
                width = bounds.get("Width", 0)
                height = bounds.get("Height", 0)
                if 100 < width < 800 and 100 < height < 800:
                    # 弹窗通常比主窗口小，过滤出合理尺寸的窗口
                    candidates.append({
                        "rect": (int(bounds["X"]), int(bounds["Y"]), int(width), int(height)),
                        "size": width * height,
                        "owner": owner,
                    })

        if not candidates:
            print("⚠️ 未找到弹窗窗口，继续使用主窗口")
            return False

        # 取最大的候选弹窗（通常就是对话框）
        candidates.sort(key=lambda x: x["size"], reverse=True)
        popup = candidates[0]
        self._window_rect = popup["rect"]
        # 切换后重建 verifier
        self._verifier = verify.StepVerifier(
            self._window_rect, context=self.app_context
        )
        print(f"🔀 已切换到弹窗窗口：{popup['rect']}")
        return True

    def switch_to_main(self):
        """恢复截图区域到主窗口（与 switch_to_popup 配对使用）"""
        if hasattr(self, '_main_window_rect') and self._main_window_rect:
            self._window_rect = self._main_window_rect
            self._verifier = verify.StepVerifier(
                self._window_rect, context=self.app_context
            )
            self._main_window_rect = None
            print("🔀 已恢复到主窗口")

    def find_and_click(self, element_desc: str, verify_desc: str = None) -> bool:
        """
        在当前窗口中查找元素并点击 — 最常用的组合操作。

        参数:
            element_desc: 要找的元素描述
            verify_desc: 可选，点击后验证的期望状态

        返回:
            是否成功
        """
        import time as _time

        # 截图
        t0 = _time.time()
        img = self.screenshot()
        if not img:
            return False
        print(f"⏱️ [截图] 耗时：{_time.time() - t0:.1f}s")

        # AI 视觉定位
        self.check_cancel()
        t0 = _time.time()
        coords = vision.find_element_with_retry(
            img, element_desc, self.app_context
        )
        print(f"⏱️ [AI视觉定位: {element_desc[:20]}...] 耗时：{_time.time() - t0:.1f}s")
        if not coords:
            return False

        # 点击 (使用产生该截图的配套扩边 rect 进行精确换算)
        self.check_cancel()
        target_rect = getattr(self, '_last_screenshot_rect', self._window_rect)
        actions.click_at_normalized(target_rect, coords)

        # 验证（如果需要）
        if verify_desc and self._verifier:
            t0 = _time.time()
            result = self._verifier.verify(verify_desc)
            print(f"⏱️ [截图验证: {verify_desc[:20]}...] 耗时：{_time.time() - t0:.1f}s")
            return result

        return True

    def find_text_input_by_accessibility(
        self,
        search_rect: tuple[float, float, float, float] | None = None,
        placeholder_keywords: tuple[str, ...] = (),
        prefer_bottom: bool = True,
    ) -> dict | None:
        """
        用 macOS Accessibility 找文本输入控件。

        这不是截图识别，也不是固定坐标，而是系统级 UI 控件命中：
        在指定区域内探测 AXTextArea / AXTextField，返回控件矩形和建议点击点。

        参数:
            search_rect: 物理坐标区域；为空时使用当前应用窗口
            placeholder_keywords: 可选 hint 文案，如 ("要求后续变更",)
            prefer_bottom: True 时优先从底部向上探测，适合聊天输入框
        """
        if not self._window_rect:
            return None

        context = self._get_accessibility_context()
        if not context:
            return None

        AS, app = context
        rect = search_rect or self._window_rect

        focused = self._ax_attr(AS, app, "AXFocusedUIElement")
        focused_match = self._text_input_candidate(AS, focused, rect, placeholder_keywords)
        if focused_match:
            focused_match["source"] = "focused"
            return focused_match

        for px, py in self._iter_text_input_probe_points(rect, prefer_bottom=prefer_bottom):
            try:
                err, element = AS.AXUIElementCopyElementAtPosition(app, px, py, None)
            except Exception:
                continue
            if err != 0 or element is None:
                continue

            match = self._text_input_candidate(AS, element, rect, placeholder_keywords)
            if match:
                match["source"] = "hit_test"
                match["probe"] = (px, py)
                return match

        return None

    def click_text_input_by_accessibility(
        self,
        search_rect: tuple[float, float, float, float] | None = None,
        placeholder_keywords: tuple[str, ...] = (),
        label: str = "文本输入框",
        prefer_bottom: bool = True,
    ) -> bool:
        """找到并点击文本输入控件。"""
        match = self.find_text_input_by_accessibility(
            search_rect=search_rect,
            placeholder_keywords=placeholder_keywords,
            prefer_bottom=prefer_bottom,
        )
        if not match:
            print(f"⚠️ [AX文本输入] 未找到 {label}")
            return False

        x, y = match["point"]
        rect = match.get("rect")
        probe = match.get("probe")
        print(
            f"🧭 [AX文本输入] {label} role={match.get('role')} "
            f"source={match.get('source')} "
            f"probe={tuple(round(v) for v in probe) if probe else None} "
            f"rect={tuple(round(v) for v in rect) if rect else None} "
            f"click=({x:.0f}, {y:.0f})"
        )
        actions.click_at_physical(x, y, delay=0.2)
        return True

    def _get_accessibility_context(self):
        try:
            import ApplicationServices as AS
            from Quartz import (
                CGWindowListCopyWindowInfo,
                kCGWindowListOptionOnScreenOnly,
                kCGNullWindowID,
            )
        except Exception as e:
            print(f"⚠️ [AX文本输入] 无法加载 Accessibility：{e}")
            return None

        try:
            if hasattr(AS, "AXIsProcessTrusted") and not AS.AXIsProcessTrusted():
                print("⚠️ [AX文本输入] 当前进程没有辅助功能权限")
                return None

            window_list = CGWindowListCopyWindowInfo(
                kCGWindowListOptionOnScreenOnly, kCGNullWindowID
            )
            pid = None
            for item in window_list:
                owner = item.get("kCGWindowOwnerName", "")
                if not any(alias.lower() in owner.lower() for alias in self.app_aliases):
                    continue

                bounds = item.get("kCGWindowBounds", {})
                candidate = (
                    int(bounds.get("X", 0)),
                    int(bounds.get("Y", 0)),
                    int(bounds.get("Width", 0)),
                    int(bounds.get("Height", 0)),
                )
                if self._rects_close(self._window_rect, candidate):
                    pid = item.get("kCGWindowOwnerPID")
                    break

            if not pid:
                return None

            return AS, AS.AXUIElementCreateApplication(pid)
        except Exception as e:
            print(f"⚠️ [AX文本输入] 获取应用上下文失败：{e}")
            return None

    def _iter_text_input_probe_points(
        self,
        rect: tuple[float, float, float, float],
        prefer_bottom: bool = True,
    ):
        x, y, w, h = rect
        x_ratios = (0.06, 0.10, 0.16, 0.24, 0.38, 0.55)
        bottom_first = (0.92, 0.90, 0.88, 0.85, 0.82, 0.78, 0.72, 0.64, 0.52, 0.38)
        top_first = tuple(reversed(bottom_first))
        y_ratios = bottom_first if prefer_bottom else top_first

        for yr in y_ratios:
            for xr in x_ratios:
                yield x + w * xr, y + h * yr

    def _text_input_candidate(
        self,
        AS,
        element,
        search_rect: tuple[float, float, float, float],
        placeholder_keywords: tuple[str, ...],
    ) -> dict | None:
        if element is None:
            return None

        role = str(self._ax_attr(AS, element, "AXRole") or "")
        if role not in {"AXTextArea", "AXTextField", "AXComboBox"}:
            return None

        rect = self._ax_rect(AS, element)
        if not rect or not self._rect_intersects(rect, search_rect):
            return None

        text_parts = [
            self._ax_attr(AS, element, "AXValue"),
            self._ax_attr(AS, element, "AXPlaceholderValue"),
            self._ax_attr(AS, element, "AXTitle"),
            self._ax_attr(AS, element, "AXDescription"),
        ]
        text = "\n".join(str(part) for part in text_parts if part is not None)
        if placeholder_keywords and text:
            if not any(keyword in text for keyword in placeholder_keywords):
                # hint 没匹配不直接否定，因为不少 Electron 控件只暴露 role 和 rect。
                pass

        tx, ty, tw, th = rect
        click_x = tx + min(28, max(12, tw * 0.05))
        click_y = ty + min(24, max(12, th * 0.55))
        return {
            "role": role,
            "rect": rect,
            "point": (click_x, click_y),
            "text": text,
        }

    def _rect_intersects(
        self,
        a: tuple[float, float, float, float],
        b: tuple[float, float, float, float],
    ) -> bool:
        ax, ay, aw, ah = a
        bx, by, bw, bh = b
        return ax < bx + bw and ax + aw > bx and ay < by + bh and ay + ah > by

    def _rects_close(
        self,
        a: tuple[float, float, float, float],
        b: tuple[float, float, float, float],
        tolerance: int = 8,
    ) -> bool:
        return all(abs(float(a[i]) - float(b[i])) <= tolerance for i in range(4))

    def _ax_rect(self, AS, element) -> tuple[float, float, float, float] | None:
        try:
            err_p, pos = AS.AXUIElementCopyAttributeValue(element, "AXPosition", None)
            err_s, size = AS.AXUIElementCopyAttributeValue(element, "AXSize", None)
            if err_p != 0 or err_s != 0:
                return None
            ok_p, point = AS.AXValueGetValue(pos, AS.kAXValueCGPointType, None)
            ok_s, sz = AS.AXValueGetValue(size, AS.kAXValueCGSizeType, None)
            if not ok_p or not ok_s:
                return None
            return (float(point.x), float(point.y), float(sz.width), float(sz.height))
        except Exception:
            return None

    def _ax_attr(self, AS, element, name: str):
        try:
            err, value = AS.AXUIElementCopyAttributeValue(element, name, None)
            return value if err == 0 else None
        except Exception:
            return None

    def read_content(self, question: str) -> str | None:
        """读取当前窗口中的信息"""
        img = self.screenshot()
        if not img:
            return None
        return vision.read_screen_content(img, question, self.app_context)

    def execute(self, intent_name: str, slots: dict, cancel_check=None) -> dict:
        """
        执行指定意图。

        参数:
            intent_name: 意图名称
            slots: 提取到的参数
            cancel_check: 中断探针闭包

        返回:
            {"success": bool, "message": str, "data": any}
        """
        self._cancel_check = cancel_check
        if intent_name not in self._intents:
            return {
                "success": False,
                "message": f"{self.app_name} 不支持操作：{intent_name}",
                "data": None,
            }

        # 调用对应的执行方法：execute_{intent_name}
        method_name = f"execute_{intent_name}"
        method = getattr(self, method_name, None)
        if not method:
            return {
                "success": False,
                "message": f"操作 {intent_name} 尚未实现",
                "data": None,
            }

        try:
            return method(slots)
        except UserCancelException as e:
            print(f"🛑 [强行中断] 任务已在底层被安全拦截隔离！")
            return {
                "success": False,
                "message": str(e),
                "data": None,
            }
        except Exception as e:
            # 🚨 FailSafeException 必须穿透所有 except，不能被吞掉
            import pyautogui
            if isinstance(e, pyautogui.FailSafeException):
                print("🚨 [FAILSAFE 触发] 物理紧急中断 — 鼠标到达左上角，任务强制终止")
                raise  # 让它继续往上传播，彻底中止整个任务链
            return {
                "success": False,
                "message": f"执行 {intent_name} 时出错：{e}",
                "data": None,
            }

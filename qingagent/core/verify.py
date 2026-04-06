from __future__ import annotations

"""
操作验证模块 — 多步操作的截图确认机制

核心思路：每执行一步操作后，重新截图让 AI 判断当前状态，
确认操作是否成功，再决定下一步。解决 sleep 盲等的问题。
"""
import os
import time
from datetime import datetime
from .. import config
from . import vision


class StepVerifier:
    """
    操作步骤验证器。

    用法:
        verifier = StepVerifier(window_rect)

        # 执行操作
        actions.click_at_normalized(rect, coords)

        # 验证操作结果
        success = verifier.verify(
            expected="聊天窗口已打开，显示了消息列表",
            fail_hint="可能未点击到正确的联系人"
        )
    """

    def __init__(self, rect: tuple, context: str = "软件截图", save_debug: bool = True):
        """
        参数:
            rect: 窗口 (x, y, w, h)
            context: 截图上下文描述
            save_debug: 是否保存调试截图
        """
        self.rect = rect
        self.context = context
        self.save_debug = save_debug
        self.step_count = 0

    def verify(
        self,
        expected: str,
        fail_hint: str = "",
        max_wait: float = 3.0,
        check_interval: float = 0.8,
    ) -> bool:
        """
        截图确认当前状态是否符合预期。

        参数:
            expected: 期望看到的状态描述，如 "聊天窗口已打开"
            fail_hint: 失败时的提示
            max_wait: 最大等待时间（秒）
            check_interval: 检查间隔（秒）

        返回:
            True = 确认成功，False = 超时未达预期
        """
        self.step_count += 1
        start_time = time.time()

        while time.time() - start_time < max_wait:
            # 截图
            save_path = None
            if self.save_debug:
                os.makedirs(config.DEBUG_SCREENSHOT_DIR, exist_ok=True)
                timestamp = datetime.now().strftime("%H%M%S")
                save_path = os.path.join(
                    config.DEBUG_SCREENSHOT_DIR,
                    f"step{self.step_count}_{timestamp}.png",
                )

            img = vision.capture_screenshot(self.rect, save_path=save_path)
            if not img:
                time.sleep(check_interval)
                continue

            # 让 AI 判断当前状态
            answer = vision.read_screen_content(
                img,
                f"请判断当前界面是否满足这个条件：{expected}\n只回答'是'或'否'，并简要说明理由。",
                self.context,
            )

            if answer and "是" in answer[:5]:
                print(f"✅ [步骤{self.step_count}] 验证通过：{expected}")
                return True

            time.sleep(check_interval)

        print(f"⚠️ [步骤{self.step_count}] 验证超时：{expected}")
        if fail_hint:
            print(f"   💡 提示：{fail_hint}")
        return False

    def capture_current(self) -> str | None:
        """截取当前窗口状态（用于后续分析或返回给用户）"""
        return vision.capture_screenshot(self.rect)

    def read_current(self, question: str) -> str | None:
        """读取当前窗口中的信息"""
        img = vision.capture_screenshot(self.rect)
        if not img:
            return None
        return vision.read_screen_content(img, question, self.context)

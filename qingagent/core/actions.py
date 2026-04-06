from __future__ import annotations

"""
操作执行模块 — 点击、输入、按键等原子操作

所有与屏幕交互的物理操作都在这里。
坐标转换：归一化坐标 (0-1000) → 物理像素坐标。
"""
import time
import pyautogui
import pyperclip
from .. import config


def normalized_to_physical(rect: tuple, nx: int, ny: int) -> tuple[float, float]:
    """
    将归一化坐标转换为物理屏幕坐标。

    参数:
        rect: (x, y, w, h) 窗口物理坐标
        nx: 归一化 x 坐标 (0-1000)
        ny: 归一化 y 坐标 (0-1000)

    返回:
        (physical_x, physical_y) 物理屏幕坐标
    """
    px = rect[0] + (nx / 1000) * rect[2]
    py = rect[1] + (ny / 1000) * rect[3]
    return px, py


def click_at_normalized(rect: tuple, coords: dict, delay: float = None):
    """
    在归一化坐标位置执行点击。

    参数:
        rect: 窗口 (x, y, w, h)
        coords: {"rx": 0-1000, "ry": 0-1000}
        delay: 点击后等待时间（秒），None 使用默认值
    """
    px, py = normalized_to_physical(rect, coords["rx"], coords["ry"])
    print(f"🖱️ 点击 → ({px:.0f}, {py:.0f})")
    pyautogui.click(px, py)
    time.sleep(delay or config.ACTION_DELAY)


def click_at_physical(x: float, y: float, delay: float = None):
    """
    在物理坐标直接点击。

    参数:
        x, y: 屏幕物理坐标
        delay: 点击后等待
    """
    pyautogui.click(x, y)
    time.sleep(delay or config.ACTION_DELAY)


def double_click_at_normalized(rect: tuple, coords: dict, delay: float = None):
    """双击指定归一化坐标位置"""
    px, py = normalized_to_physical(rect, coords["rx"], coords["ry"])
    print(f"🖱️ 双击 → ({px:.0f}, {py:.0f})")
    pyautogui.doubleClick(px, py)
    time.sleep(delay or config.ACTION_DELAY)


def right_click_at_normalized(rect: tuple, coords: dict, delay: float = None):
    """右击指定归一化坐标位置"""
    px, py = normalized_to_physical(rect, coords["rx"], coords["ry"])
    print(f"🖱️ 右击 → ({px:.0f}, {py:.0f})")
    pyautogui.rightClick(px, py)
    time.sleep(delay or config.ACTION_DELAY)


def type_text(text: str):
    """
    通过剪贴板粘贴文本 — 避免 pyautogui.write() 的中文兼容问题。

    参数:
        text: 要输入的文本（支持中文）
    """
    pyperclip.copy(text)
    pyautogui.hotkey("command", "v")
    time.sleep(0.3)
    print(f"⌨️ 已输入：{text[:50]}{'...' if len(text) > 50 else ''}")


def press_key(key: str, delay: float = 0.3):
    """
    按下指定按键。

    参数:
        key: 按键名称，如 "enter", "tab", "escape"
        delay: 按键后等待
    """
    pyautogui.press(key)
    time.sleep(delay)


def hotkey(*keys, delay: float = 0.3):
    """
    组合键操作。

    参数:
        keys: 按键序列，如 ("command", "c")
        delay: 操作后等待
    """
    pyautogui.hotkey(*keys)
    time.sleep(delay)


def move_to(rect: tuple, coords: dict, duration: float = 0.5):
    """
    移动鼠标到指定位置（不点击）。

    参数:
        rect: 窗口 (x, y, w, h)
        coords: 归一化坐标
        duration: 移动动画时长
    """
    px, py = normalized_to_physical(rect, coords["rx"], coords["ry"])
    pyautogui.moveTo(px, py, duration=duration)


def scroll(clicks: int, rect: tuple = None, coords: dict = None):
    """
    滚动操作。

    参数:
        clicks: 正数向上滚，负数向下滚
        rect: 可选，先移到指定窗口位置再滚
        coords: 可选，配合 rect 使用
    """
    if rect and coords:
        px, py = normalized_to_physical(rect, coords["rx"], coords["ry"])
        pyautogui.moveTo(px, py, duration=0.2)
    pyautogui.scroll(clicks)
    time.sleep(config.ACTION_DELAY)

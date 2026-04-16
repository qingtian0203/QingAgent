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

# ============================================================
#  物理紧急安全锁
# ============================================================
# FAILSAFE = True：把鼠标移到屏幕左上角(0,0)会立刻抛出
# pyautogui.FailSafeException，中断所有 pyautogui 操作。
# 这是对抗"任务陷入死循环"的最后物理手段。
pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.05   # 每次 pyautogui 操作间最短间隔（防止操作过快系统跟不上）


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
    
    # 将瞬间点击改为带短暂停留的点击，避免 Electron 菜单吃掉由于过快导致的点击事件
    pyautogui.mouseDown(px, py)
    time.sleep(0.05)
    pyautogui.mouseUp(px, py)
    
    time.sleep(delay or config.ACTION_DELAY)


def click_at_physical(x: float, y: float, delay: float = None):
    """
    在物理坐标直接点击。

    参数:
        x, y: 屏幕物理坐标
        delay: 点击后等待
    """
    pyautogui.mouseDown(x, y)
    time.sleep(0.05)
    pyautogui.mouseUp(x, y)
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

    ⚠️ 注意：在 macOS 下，如果当前输入法是腾讯微信输入法(WeType)，
    粘贴触发的 insertText: 回调会访问已释放的 Tkinter NSWindow 对象
    导致 EXC_BAD_ACCESS (SIGSEGV) Crash。
    修复方案：粘贴前强制切换到系统 ABC 输入法，完成后切回。

    参数:
        text: 要输入的文本（支持中文）
    """
    import subprocess
    # 切换到系统 ABC 输入法（安全），避免 WeType 与 Tkinter 的兼容性 crash
    subprocess.run(
        ["osascript", "-e",
         'tell application "System Events" to key code 49 using {control down, shift down}'],
        capture_output=True, timeout=3
    )
    time.sleep(0.15)
    
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


def drag_normalized(rect: tuple, start_coords: dict, end_coords: dict, duration: float = 1.0):
    """
    按住鼠标左键，从起点拖拽到终点后松开（可用于画框、长按划动等）。

    参数:
        rect: 窗口 (x, y, w, h)
        start_coords: 起点归一化坐标 {"rx": ..., "ry": ...}
        end_coords: 终点归一化坐标 {"rx": ..., "ry": ...}
        duration: 滑动/拖拽的动画耗时（秒），越长动作越慢越能给系统反应时间
    """
    sx, sy = normalized_to_physical(rect, start_coords["rx"], start_coords["ry"])
    ex, ey = normalized_to_physical(rect, end_coords["rx"], end_coords["ry"])
    
    print(f"🖱️ 拖拽滑动 → 从 ({sx:.0f}, {sy:.0f}) 到 ({ex:.0f}, {ey:.0f})，耗时 {duration}s")
    
    # 瞬间移动到起点
    pyautogui.moveTo(sx, sy)
    # 按住左键平滑拖到终点并松开
    pyautogui.dragTo(ex, ey, duration=duration, button='left')
    time.sleep(config.ACTION_DELAY)


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


def emergency_stop():
    """
    全局紧急终止 — 立刻中断正在进行的所有 pyautogui 操作。

    触发机制：
    1. 先发 Escape 键，关闭正在弹出的截图工具遮罩、弹框等
    2. 把鼠标移到屏幕左上角(0,0)，触发 pyautogui.FAILSAFE 机制
       → 所有 pyautogui 操作立即抛出 FailSafeException 并中断

    ⚠️ 不要在正常业务流程中调用，仅用于紧急情况。
    """
    try:
        # 先尝试按 Escape 关闭截图工具等弹出遮罩
        pyautogui.press("escape")
        time.sleep(0.2)
        pyautogui.press("escape")
        time.sleep(0.1)
    except Exception:
        pass

    try:
        # 把鼠标甩到左上角，触发 FAILSAFE 抛出异常
        # 这会中断同一线程内所有后续的 pyautogui 操作
        pyautogui.moveTo(0, 0, duration=0.1)
    except Exception:
        pass

    print("🚨 [紧急终止] 已触发 FAILSAFE，所有 pyautogui 操作已中断")


def copy_image_to_clipboard(image_path: str) -> bool:
    """
    将本地图片文件强制写入 macOS 系统剪贴板（清空之前的文本保留）。
    用于精确发送刚截取的图片，防止剪贴板在其间被中途搜索文本污染。
    """
    import subprocess
    import os
    if not os.path.exists(image_path):
        print(f"❌ 找不到图片文件：{image_path}")
        return False
        
    try:
        # 使用 macOS 内置的 osascript 将本地文件加载至剪贴板
        script = f'''
        set theFile to POSIX file "{image_path}"
        set the clipboard to (read theFile as «class PNGf»)
        '''
        res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
        if res.returncode == 0:
            print(f"📋 图片已硬塞入剪贴板：{image_path}")
            return True
        else:
            print(f"⚠️ AppleScript 写入剪贴板失败: {res.stderr}")
            return False
    except Exception as e:
        print(f"⚠️ 无法将图片写入剪贴板: {e}")
        return False

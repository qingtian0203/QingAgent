from __future__ import annotations

"""
窗口管理模块 — 发现、激活、定位桌面应用窗口

基于 macOS Quartz API，通过进程名模糊匹配找到目标窗口，
返回窗口的物理坐标和尺寸。
"""
import os
import time
from Quartz import (
    CGWindowListCopyWindowInfo,
    kCGWindowListOptionOnScreenOnly,
    kCGNullWindowID,
)
from .. import config


def find_window(app_aliases: list[str], _retry_count: int = 0, silent: bool = False) -> dict | None:
    """
    在屏幕上查找匹配的应用窗口。

    参数:
        app_aliases: 应用名称列表（支持模糊匹配），如 ["微信", "WeChat"]
        silent: 为 True 时不打印找不到窗口的日志（轮询场景使用）

    返回:
        {"rect": (x, y, w, h), "owner": "进程名"} 或 None
    """
    window_list = CGWindowListCopyWindowInfo(
        kCGWindowListOptionOnScreenOnly, kCGNullWindowID
    )
    found = []
    all_owners = set()

    for window in window_list:
        owner = window.get("kCGWindowOwnerName", "")
        all_owners.add(owner)

        # 模糊匹配：别名列表中任意一个命中即可
        if any(alias.lower() in owner.lower() for alias in app_aliases):
            bounds = window.get("kCGWindowBounds", {})
            w = bounds.get("Width", 0)
            h = bounds.get("Height", 0)
            if w > 40:  # 过滤掉菜单栏等极小窗口
                found.append({
                    "rect": (int(bounds["X"]), int(bounds["Y"]), int(w), int(h)),
                    "size": w * h,
                    "owner": owner,
                })

    if not found:
        if not silent:
            print(f"❌ 找不到匹配 {app_aliases} 的窗口")
            print("📋 当前屏幕可见进程：")
            for name in sorted(list(all_owners))[:15]:
                print(f"   - {name}")
        return None

    # 按面积排序，取最大的（通常是主窗口）
    found.sort(key=lambda x: x["size"], reverse=True)
    best = found[0]

    # 如果窗口太小，可能是缩略图，尝试点击唤醒
    if best["rect"][2] < config.MIN_WINDOW_WIDTH:
        if _retry_count > 3:
            print(f"❌ 唤醒缩略图失败多次，强行返回当前窗口大小。")
            return {"rect": best["rect"], "owner": best["owner"]}

        print(f"⚠️ 检测到 {best['owner']} 缩略图（宽: {best['rect'][2]}, 高: {best['rect'][3]}），尝试唤醒... ({_retry_count + 1}/3)")
        import pyautogui
        cx = best["rect"][0] + best["rect"][2] / 2
        cy = best["rect"][1] + best["rect"][3] / 2
        try:
            pyautogui.click(cx, cy)
        except Exception as e:
            print(f"点击唤醒出错 (大概率无辅助功能权限): {e}")
        time.sleep(config.THUMBNAIL_WAKE_DELAY)
        return find_window(app_aliases, _retry_count + 1)  # 递归重新查找

    return {"rect": best["rect"], "owner": best["owner"]}


def activate_app(app_name: str) -> bool:
    """
    激活（前置）指定应用，并强制弹出主窗口。

    参数:
        app_name: 应用名称，如 "WeChat" 或 "微信"

    返回:
        是否成功
    """
    import subprocess

    # open -a：等同于双击 Dock 图标，是最可靠的弹出主窗口方式
    # 对于微信这类关闭台前调度后无响应 reopen 的 App 尤为有效
    ret_open = subprocess.run(["open", "-a", app_name], capture_output=True).returncode

    # osascript activate：切到前台（open -a 有时不会自动前置）
    os.system(f'osascript -e \'tell application "{app_name}" to activate\' 2>/dev/null')

    if ret_open == 0:
        print(f"✅ 已激活应用：{app_name}")
        time.sleep(config.APP_SWITCH_DELAY)
        return True
    else:
        print(f"⚠️ 激活 {app_name} 失败（可能名称不对），尝试继续...")
        return False


def activate_and_find(app_aliases: list[str]) -> dict | None:
    """
    激活应用并找到其窗口 — 组合常用流程。

    参数:
        app_aliases: 应用名称别名列表，第一个会用来激活

    返回:
        {"rect": (x, y, w, h), "owner": "进程名"} 或 None
    """
    # 尝试用别名激活，成功一个就停
    for alias in app_aliases:
        if activate_app(alias):
            break

    return find_window(app_aliases)

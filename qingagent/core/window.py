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



def resolve_app_real_name(app_name: str) -> str:
    """
    动态破解 macOS 的本地化屏障：
    根据输入的任意别名/中文名，利用 Spotlight 底层引擎精准查出 app 真实的包名（如 备忘录 -> Notes）
    """
    import subprocess
    if not app_name:
        return app_name

    # shell=False 防止 app_name 含单引号等特殊字符时产生 Shell 注入或查询断裂
    # Python 列表推导替代管道 head -n 1，无需依赖 Shell
    try:
        # 1. 优先精确匹配（解决"备忘录"被"语音备忘录"抢行的问题）
        exact_query = (
            f"kMDItemContentType == 'com.apple.application-bundle' "
            f"&& kMDItemDisplayName == '{app_name}.app'c"
        )
        res = subprocess.run(
            ["mdfind", exact_query],
            capture_output=True, text=True, timeout=2
        ).stdout.strip()
        res = next((line for line in res.splitlines() if line.endswith(".app")), "")

        # 2. 精确未命中，执行模糊匹配
        if not res:
            fuzzy_query = (
                f"kMDItemContentType == 'com.apple.application-bundle' "
                f"&& kMDItemDisplayName == '*{app_name}*'c"
            )
            res = subprocess.run(
                ["mdfind", fuzzy_query],
                capture_output=True, text=True, timeout=2
            ).stdout.strip()
            res = next((line for line in res.splitlines() if line.endswith(".app")), "")

        if res and res.endswith(".app"):
            # 拿到 /System/Applications/Notes.app -> 抽取 Notes
            real_name = os.path.basename(res)[:-4]
            return real_name
    except Exception as e:
        print(f"⚠️ mdfind 解析异常: {e}")
        
    return app_name  # 如果查不到，原样返回兜底

def activate_app(app_name: str, resolved: bool = False) -> bool:
    """
    激活（前置）指定应用，并强制弹出主窗口。
    """
    import subprocess

    # 先做一层智能解析，获得真实的系统进程包名
    real_app_name = resolve_app_real_name(app_name) if not resolved else app_name

    # open -a：等同于双击 Dock 图标，是最可靠的弹出主窗口方式
    ret_open = subprocess.run(["open", "-a", real_app_name], capture_output=True).returncode

    # osascript activate：切到前台。加上 & 放入后台执行，绝不让缓慢的 AppleEvent 事件阻断 Python 的主线程并发帧率！
    import os as _os
    _os.system(f'osascript -e \'tell application "{real_app_name}" to activate\' >/dev/null 2>&1 &')

    if ret_open == 0:
        print(f"✅ 已激活应用：{real_app_name}" + (f" (原名:{app_name})" if real_app_name != app_name else ""))
        # 抛弃保守的 1.5s 全局硬中断，只给予极小时间的 CPU 缓冲
        time.sleep(0.1)
        return True
    else:
        print(f"⚠️ 激活 {real_app_name} 失败，尝试继续...")
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

# AppleScript 进程级快捷键注入

## 问题场景

当目标应用（如微信）切换到前台后，焦点可能停留在**内嵌 WebView**（文章、公众号页面）里，
此时用 `pyautogui.hotkey()` 或 `actions.hotkey()` 发出的快捷键会打到 WebView，而不是主应用。

## 错误做法：依赖焦点

```python
# ❌ 焦点可能不在微信主界面，Cmd+F 打到 WebView 的搜索
actions.hotkey("command", "f")
```

## 正确做法：进程级注入

```python
import subprocess

inject_script = '''
tell application "System Events"
    tell process "WeChat"
        keystroke "f" using command down
    end tell
end tell
'''
subprocess.run(["osascript", "-e", inject_script],
               capture_output=True, text=True, timeout=5)
```

## 原理

`tell process "ProcessName"` 把 keystroke 事件直接塞进目标进程的事件队列，
**完全绕过当前焦点路由**，不管焦点在主窗口、子窗口还是 WebView，都能正确触达。

## 常用修饰键写法

| 快捷键 | AppleScript 写法 |
|---|---|
| Cmd+F | `keystroke "f" using command down` |
| Cmd+Shift+F | `keystroke "f" using {command down, shift down}` |
| Enter | `key code 36` |
| Escape | `key code 53` |

## 应用场景

- 微信切后台再切回，焦点在公众号文章 → 注入 Cmd+F 打开全局搜索 ✅
- 任何需要向特定进程发快捷键而不依赖焦点的场景

## 参考实现

`qingagent/skills/wechat.py` → `_find_contact_by_search()` 中的 `search_inject_script`

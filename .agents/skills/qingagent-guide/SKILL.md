---
name: QingAgent 自动化助手开发指南
description: QingAgent 的架构设计、Skill 开发规范、Planner 调优、权限配置和常见问题排查指南。新增或修改 Skill 前必读。
---

# QingAgent 开发指南

## 项目路径

| 资源 | 路径 |
|------|------|
| **源码根目录** | `/Users/konglingjia/AIProject/QingAgent/` |
| **虚拟环境** | `venv/bin/python3` |
| **主配置** | `qingagent/config.py` |
| **Skill 目录** | `qingagent/skills/` |
| **核心引擎** | `qingagent/core/` |
| **Web 服务** | `qingagent/server/app.py` |

## 关键配置（config.py）

```python
# AI 后端（视觉+意图解析均用同一套）
API_MODE      = "openai"                         # 当前已切换至 oMLX（OpenAI 兼容）
OLLAMA_URL    = "http://localhost:8000/v1"        # oMLX 地址（Vision + Planner 共用）
API_KEY       = "68686688v"                       # oMLX API Key
VISION_MODEL  = "gemma-4-26b-a4b-it-4bit"        # 已切换至本机 MLX 模型
PLANNER_MODEL = "gemma-4-26b-a4b-it-4bit"        # 同上
PLANNER_URL   = "http://localhost:8000/v1"        # 同 oMLX 地址

SERVER_PORT   = 8077            # Web 服务端口（固定，不随网络变化）
MIN_WINDOW_WIDTH = 400          # 低于此宽度判定为缩略图（尝试唤醒）
APP_SWITCH_DELAY = 1.5          # 切换应用后等待（秒）
ACTION_DELAY     = 0.6          # 每次点击后等待（秒）
THUMBNAIL_WAKE_DELAY = 1.5      # 缩略图唤醒点击后等待（秒）
```

### 切换 AI 后端

| 目标后端 | API_MODE | OLLAMA_URL |
|---------|----------|------------|
| 本机 oMLX（当前默认） | `"openai"` | `"http://localhost:8000/v1"` |
| 本机 Ollama | `"ollama"` | `"http://localhost:11434/api/generate"` |

> 两个配置的 URL 含义不同：oMLX 填 `/v1`（会自动补全 `/chat/completions`）；Ollama 填 `/api/generate`。

## 架构流程

```
用户指令（自然语言）
    ↓
Planner.parse_intent()   # LLM 解析 → {app, intent, slots, confidence}
    ↓
SkillRegistry.get_skill_by_name(app)
    # 先精确匹配 app_name，再匹配 app_aliases（不区分大小写）
    ↓
skill.execute(intent_name, slots)
    ├── activate_and_find(app_aliases)
    │     ├── activate_app()  →  osascript: tell app to activate + reopen
    │     └── find_window()   →  CGWindowListCopyWindowInfo 查找最大面积窗口
    │           └── 宽度 < MIN_WINDOW_WIDTH？→ 点击唤醒（最多重试 3 次）
    ├── 快捷键定位输入框（推荐，~0.3s）
    └── vision.find_element() AI视觉兜底（三段显微精准定位）
```

## 已注册的 Skill 列表

| Skill | app_name | 主要 intent |
|-------|----------|-------------|
| `WeChatSkill` | 微信 | `send_message`（含剪贴板图片发送） |
| `BrowserSkill` | 浏览器 | `open_url`、`search`、`play_24point` |
| `AntigravitySkill` | Antigravity | `send_prompt` |
| `QingTianUtilSkill` | 晴天Util | `click_feature`、`check_calendar`、`add_calendar`、`pull_and_restart` |
| `OSControlSkill` | System | `custom_screenshot`（QQ截图划框）、`app_screenshot`（窗口吸附截图） |

## Skill 开发规范

### 1. 继承 BaseSkill

```python
class MySkill(BaseSkill):
    app_name = "MyApp"                              # 唯一标识（注册 key）
    app_aliases = ["MyApp", "my", "我的应用"]        # 别名（Planner 和查找都用）
    app_context = "MyApp 应用界面截图"               # 视觉识别时的提示词前缀
```

### 2. 注册 Intent

```python
def register_intents(self):
    self.add_intent(Intent(
        name="send_message",           # 意图名（小写下划线）
        description="发送消息",         # 给 Planner AI 看的描述（影响识别准确率）
        required_slots=["message"],    # 必需参数
        optional_slots=["contact"],    # 可选参数
        examples=[                     # 示例（Few-shot，提升小模型准确率）
            "给MyApp发消息说 你好",
            "让MyApp发送 测试",
        ],
    ))
```

### 3. 实现执行方法

方法命名规则：`execute_<intent_name>(self, slots: dict) -> dict`

```python
def execute_send_message(self, slots: dict) -> dict:
    message = slots["message"]
    
    if not self.activate():
        return {"success": False, "message": "无法激活应用", "data": None}
    
    # 定位输入框、输入内容、发送...
    
    return {"success": True, "message": f"已发送：{message}", "data": None}
```

### 4. 注册到 SkillRegistry

在 `qingagent/skills/__init__.py` 的 `auto_register()` 中追加：

```python
from .my_skill import MySkill

def auto_register(self):
    ...
    self.register(MySkill())
```

## 视觉引擎升级：三段显微精准定位

`vision.find_element()` 已升级为"三段防偏锁心微操策略"，精准度大幅提升：

```
段1 - 全景粗寻（全图）   → 定粗略中心点（易偏移）
段2 - 300×300 包容纠偏  → 截取 300px 局部精修
段3 - 80×80 极限锁心    → 截取 80px 指甲盖强制对中
```

**新增函数 `vision.find_element_bounds()`**：直接返回元素 BoundingBox（左上+右下归一化坐标），用于拖拽画框场景（不走三段策略，避免裁图丢失外围信息）。

```python
bounds = vision.find_element_bounds(img_b64, "日志区域", context="屏幕全景")
# 返回: {"rx1": ..., "ry1": ..., "rx2": ..., "ry2": ...}
```

## BaseSkill 重要变更

### screenshot() 向外扩 200px（捕获弹窗）

`BaseSkill.screenshot()` 现在会在窗口四周**额外外扩 200px**，以捕获溢出的弹窗、下拉菜单等超出窗口边界的 UI 元素。扩展后的矩形保存在 `self._last_screenshot_rect`，供后续点击坐标换算使用。

```python
# 使用扩展截图后的真实矩形做点击换算（而不是原窗口 rect）
target_rect = getattr(self, '_last_screenshot_rect', self._window_rect)
actions.click_at_normalized(target_rect, coords)
```

## actions.py 新增操作

### `drag_normalized()` — 归一化拖拽

```python
actions.drag_normalized(
    rect,           # 窗口 (x, y, w, h)
    start_coords,   # {"rx": ..., "ry": ...}
    end_coords,     # {"rx": ..., "ry": ...}
    duration=1.5    # 拖拽时长（越长越流畅）
)
```

用于触发截图工具画框、长按拖拽等场景。

## OSControlSkill 说明（系统截图 Skill）

### custom_screenshot — 自定义区域截图（QQ截图）

1. 全屏截图感知目标区域
2. `find_element_bounds()` 获得目标的左上/右下角
3. 触发 QQ 截图热键 `Ctrl+Cmd+A`
4. `drag_normalized()` 模拟人类滑动画框
5. 框内双击 + 回车双重确认保存

```python
# 意图示例
"使用QQ截图把界面上的服务日志截存下来"
"帮我截取屏幕左侧的导航栏"
```

### app_screenshot — 应用窗口吸附截图

1. 激活目标应用
2. 全屏截图找到应用主窗口重心坐标
3. 鼠标悬停在重心处触发 `Ctrl+Cmd+A`
4. 截图工具自动边缘吸附 → 单击套牢 → 双击确认

```python
# 意图示例
"给微信截图"
"帮我把日历应用截图"
```

> 支持中英文应用名映射（微信→WeChat、日历→Calendar 等）

## WeChat Skill：剪贴板图片发送

当 `message` 参数为 `"[粘贴]"` 时，触发剪贴板图片发送逻辑（解决截图后系统剪贴板被联系人搜索覆盖的问题）：

1. 通过 **Paste** 工具（`Shift+Cmd+Space`）呼出历史剪贴板
2. 按右方向键切换到截图（历史第 2 位）
3. 回车将截图重新压入剪贴板并粘贴到聊天框

```python
# Planner 在识别"发截图/发剪贴板内容"时自动填入此参数
slots = {"contact_name": "张三", "message": "[粘贴]"}
```

> ⚠️ 此功能依赖 macOS 上安装了 **Paste** 剪贴板管理工具。

## 日历 Skill 优化：批量定位（减少截图次数）

快捷日期场景（今天/明天/后天/下周）采用**一次截图批量定位**多个元素的策略：

- 调用 `vision.find_elements_batch()` 同时定位输入框、日期按钮、确认按钮
- 截图次数从 5 次降至 1 次，AI 推理耗时大幅减少
- 批量定位失败时自动回退到逐步定位模式

## Planner Prompt 规范

`planner.py` 中的 Prompt 包含以下关键规则：

- **App 名称优先**：指令中明确提到应用名/别名时，必须使用该应用
- **发微信 vs 发消息区分**：`给xx发微信` = 微信；`给AG/Antigravity发消息` = Antigravity
- **消息内容净化**：提取 `message/prompt` 时去除"问一下"、"告诉他"等指令词
- **人称转换**：用户说"问她干嘛呢" → AI 发"你干嘛呢"
- **截图发送识别**：用户说"发刚截的图/发剪贴板内容" → `message = "[粘贴]"`

Adding 新 Skill 时，**在 examples 中加入贴近实际口语的示例**，对小模型（gemma4）尤为关键。

## 窗口查找注意事项（core/window.py）

### find_window 缩略图处理

当检测到窗口宽度 < `MIN_WINDOW_WIDTH` 时，认为是缩略图，会点击尝试唤醒。
**最多重试 3 次**，超过后强行返回该窗口（防死循环）。

### activate_app 强制弹出主窗口

使用 `reopen` 指令而非仅 `activate`，防止关闭主窗口后激活无效：

```applescript
tell application "WeChat"
    activate
    reopen   -- 强制弹出主窗口（即使主窗口被红叉关闭）
end tell
```

## Antigravity Skill 特殊说明

### 输入框定位策略（防呆设计）

由于 `Cmd+L` 在 Cursor/Antigravity 中是 Toggle（再按一次会关闭），直接按 `Cmd+L` 可能关闭输入框。

**解决方案**：先按 `Cmd+1` 把焦点强制转移到代码编辑器，再按 `Cmd+L` 打开 Agent 输入框：

```python
actions.hotkey("command", "1", delay=0.2)   # 焦点回到代码区
actions.hotkey("command", "l", delay=0.8)   # 打开/聚焦 Agent
```

### 别名列表

```python
app_aliases = ["Antigravity", "AG", "ag", "编辑器", "Cursor"]
```

## Server 修复：ThreadedHTTPServer 端口复用

`server/app.py` 已切换为 `ThreadedHTTPServer` 并开启 `SO_REUSEADDR`，防止重启时因端口未释放报 `Address already in use`。

## macOS 权限

| 权限 | 用途 | 问题场景 |
|------|------|---------| 
| **辅助功能** | 模拟鼠标/键盘 | 点击无效（静默丢弃） |
| **屏幕录制** | 截图 + CGWindowList | 窗口坐标全为 0 或极小 |

### 典型症状
- 点击后屏幕上没有任何反应
- 检测到"缩略图"尺寸（宽 111，高 121）并循环重试

### 修复方法
1. 系统设置 → 隐私与安全性 → 辅助功能（或屏幕录制）
2. 选中 `晴天 Util.app` → 点 `[-]` 删除 → 点 `[+]` 重新添加 → 开启开关

> ⚠️ 每次 py2app 重新打包后都需要重置，因为文件 Hash 变化导致 macOS 静默撤销权限。
> 晴天 Util 内置「🔧 修复 Mac 权限」按钮可一键跳转到设置页。

## 常见问题

| 现象 | 原因 | 解决 |
|------|------|------|
| 点启动服务立即变停止 | 8077 端口被旧进程占用 | 点启动服务（会自动清理）或手动 `kill -9 $(lsof -ti :8077)` |
| 微信找不到或缩略图循环 | 屏幕录制权限被撤销 | 重新授权（见上方） |
| AI 发消息到错误的应用 | 小模型识别别名失败 | 检查 examples 中是否有对应示例 |
| send_prompt 打字到了代码文件 | Cmd+L 把 Agent 关闭了 | 已修复（先 Cmd+1 再 Cmd+L） |
| UI 显示停止但服务还在跑 | 僵尸进程占用端口 | 启动按钮会自动清理，或手动 kill |
| 发截图但微信收到的是文字"[粘贴]" | 未安装 Paste 工具或剪贴板历史已满 | 安装 Paste App，或改为手动粘贴 |
| vision AI 定位偏移 | 单次推理漂移 | 已修复（三段显微精准定位策略） |
| oMLX 切换后 404 错误 | PLANNER_URL 未同步更新 | 确保 PLANNER_URL 也改为 `/v1` |

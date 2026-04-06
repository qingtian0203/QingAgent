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
PLANNER_MODEL = "qwen2.5:7b"    # 意图解析模型（轻量快速，~1.5s）
VISION_MODEL  = "gemma4:26b"    # 视觉识别模型（多模态，~15s 兜底）
SERVER_PORT   = 8077            # Web 服务端口（固定，不随网络变化）
MIN_WINDOW_WIDTH = 400          # 低于此宽度判定为缩略图（尝试唤醒）
APP_SWITCH_DELAY = 1.5          # 切换应用后等待（秒）
ACTION_DELAY     = 0.6          # 每次点击后等待（秒）
THUMBNAIL_WAKE_DELAY = 1.5      # 缩略图唤醒点击后等待（秒）
```

## 架构流程

```
用户指令（自然语言）
    ↓
Planner.parse_intent()   # Ollama 解析 → {app, intent, slots, confidence}
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
    └── vision.find_element() AI视觉兜底（~15s）
```

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

## Planner Prompt 规范

`planner.py` 中的 Prompt 包含以下关键规则：

- **App 名称优先**：指令中明确提到应用名/别名时，必须使用该应用
- **发微信 vs 发消息区分**：`给xx发微信` = 微信；`给AG/Antigravity发消息` = Antigravity
- **消息内容净化**：提取 `message/prompt` 时去除"问一下"、"告诉他"等指令词
- **人称转换**：用户说"问她干嘛呢" → AI 发"你干嘛呢"

Adding 新 Skill 时，**在 examples 中加入贴近实际口语的示例**，对小模型（qwen2.5:7b）尤为关键。

## 窗口查找注意事项（core/window.py）

### find_window 缩略图处理

当检测到窗口宽度 < `MIN_WINDOW_WIDTH` 时，认为是缩略图，会点击尝试唤醒。
**最多重试 3 次**，超过后强行返回该窗口（防死循环）。

```python
def find_window(app_aliases, _retry_count=0):
    # _retry_count 超过 3 次 → 放弃唤醒，返回现有窗口
```

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

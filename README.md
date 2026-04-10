# QingAgent — 个人 AI 自动化助手

基于本机 **MLX 大模型（oMLX）**，通过自然语言在**手机/浏览器**远程控制 Mac 上的应用（微信、浏览器、编辑器等）。支持串行任务队列、截图 HITL 确认、AI 三段视觉精准定位。

## 快速开始

```bash
cd ~/AIProject/QingAgent
source venv/bin/activate

# 启动 Web 服务（手机通过局域网访问）
python main.py serve

# 命令行模式（直接在终端交互）
python main.py cli

# 测试单条指令
python main.py test "给丸子发条微信说在吗"
```

## 访问地址

启动服务后在局域网内访问（手机和电脑需在同一 WiFi）：
```
http://<你的局域网 IP>:8077
```
IP 显示在「晴天 Util」的 AI Agent 面板中。

## 支持的指令示例

| 指令 | 效果 |
|------|------|
| `给丸子发微信说晚饭吃啥` | 打开微信，搜索"丸子"，截图预览后确认发送 |
| `给AG发消息说 帮我检查一下这段代码` | 聚焦 Antigravity 编辑器的 Agent 面板，发送指令 |
| `帮我打开百度搜一下天气` | 打开浏览器，搜索天气 |
| `给晴天Util发消息说 打开日历` | 操作晴天 Util 应用 |
| `把桌面的 demo.zip 发给晴天小米` | 文件选择 + 截图预览 + 确认发送 |
| `帮我把微信截图` | OSControlSkill 吸附应用窗口截图 |
| `截取屏幕上的服务日志` | OSControlSkill 自定义区域截图（QQ截图） |

## 支持的别名

| 应用 | 官方名 | 支持别名 |
|------|--------|---------|
| 微信 | 微信 | WeChat、wechat |
| 编辑器 | Antigravity | AG、ag、编辑器、Cursor |
| 浏览器 | 浏览器 | Safari、Chrome、browser |
| 工具 | 晴天Util | QingUtil、工具 |

## 核心特性

### 🔒 HITL（人在环路）强制确认
所有微信发送操作（文本 / 图片 / 文件）均会挂起任务，截图当前微信窗口状态，在 Web UI 中展示预览，用户点击「确认发送」后才真正执行，**彻底消除误触风险**。

### 📋 串行任务队列
使用 `queue.Queue` 实现线程安全的串行任务调度，防止多条指令并行执行时的鼠标/键盘物理冲突。多个请求会自动排队，UI 实时显示队列状态。

### 👁️ 三段显微精准视觉定位
`vision.find_element()` 采用三段递进策略，大幅减少 AI 坐标漂移：
```
段1 - 全景粗寻（全屏）   → 定粗略中心
段2 - 300×300 包容纠偏  → 截取局部精修
段3 - 80×80 极限锁心    → 强制对中，精度 ±5px
```

## 项目结构

```
QingAgent/
├── main.py                     # 主入口（serve / cli / test 三种模式）
├── qingagent/
│   ├── config.py               # 全局配置（模型、端口、延迟参数）
│   ├── memory.py               # 滑动窗口对话记忆
│   ├── planner/
│   │   └── planner.py          # AI Planner（意图解析 → 查找 Skill → 执行）
│   ├── skills/
│   │   ├── __init__.py         # SkillRegistry（注册中心 + 别名查找）
│   │   ├── base.py             # BaseSkill 基类（Intent / 能力描述 / 激活窗口）
│   │   ├── wechat.py           # 微信 Skill（含 HITL 截图确认）
│   │   ├── browser.py          # 浏览器 Skill
│   │   ├── antigravity.py      # Antigravity 编辑器 Skill
│   │   ├── qingtian_util.py    # 晴天 Util Skill
│   │   └── os_control.py       # 系统截图 Skill（QQ截图 / 窗口吸附）
│   ├── core/
│   │   ├── window.py           # 窗口查找与激活（CGWindowList + AppleScript）
│   │   ├── actions.py          # 鼠标键盘操作封装（pyautogui）
│   │   ├── vision.py           # AI 视觉识别（三段显微精准定位，oMLX 多模态）
│   │   └── verify.py           # 执行结果验证
│   └── server/
│       └── app.py              # HTTP Web 服务（任务队列 + HITL UI）
├── venv/                       # Python 虚拟环境
└── requirements.txt
```

## 配置说明

编辑 `qingagent/config.py`：

```python
# AI 后端：本机 oMLX（OpenAI 兼容，端口 8000）
API_MODE      = "openai"
OLLAMA_URL    = "http://localhost:8000/v1"   # oMLX 地址
API_KEY       = "68686688v"                  # oMLX API Key

# 视觉识别 + 意图解析（共用同一本机 MLX 模型）
VISION_MODEL  = "gemma-4-26b-a4b-it-4bit"
PLANNER_MODEL = "gemma-4-26b-a4b-it-4bit"
PLANNER_URL   = "http://localhost:8000/v1"

# Web 服务端口
SERVER_PORT = 8077
```

> 若需切换到其他 OpenAI 兼容后端（LM Studio / vLLM），只需修改 URL 和 Key 即可，`API_MODE` 保持 `"openai"`。

## 技术架构

```
用户输入（自然语言）
       ↓
  AI Planner（oMLX 意图解析，~1.5s）
       ↓
  SkillRegistry（别名匹配查找对应 Skill）
       ↓
  TaskQueue（串行队列，防并发冲突）
       ↓
  Skill.execute()
    ├── window.activate_and_find()  # 激活应用，找窗口坐标
    ├── Cmd+L / 快捷键              # 快速定位输入框（~0.3s）
    └── vision.find_element()      # AI 视觉三段定位（兜底）
    ↓（微信发送类操作）
  HITL 截图确认                    # 挂起 → 截图预览 → 用户确认 → 执行
```

## 开发指南

### 新增 Skill

参考 `qingagent/skills/browser.py`，继承 `BaseSkill` 并实现：

```python
class MyAppSkill(BaseSkill):
    app_name = "MyApp"
    app_aliases = ["MyApp", "我的应用", "app"]

    def register_intents(self):
        self.add_intent(Intent(
            name="do_something",
            description="做某件事",
            required_slots=["content"],
            examples=["让MyApp做某件事"],
        ))

    def execute_do_something(self, slots):
        if not self.activate():
            return {"success": False, "message": "无法激活应用", "data": None}
        # 实现逻辑...
        return {"success": True, "message": "完成", "data": None}
```

然后在 `skills/__init__.py` 的 `auto_register()` 中注册。

### macOS 权限要求

| 权限 | 用途 | 授权方式 |
|------|------|---------|
| 辅助功能 | 模拟鼠标/键盘点击 | 系统设置 → 隐私与安全性 → 辅助功能 |
| 屏幕录制 | 截图用于 AI 视觉识别 | 系统设置 → 隐私与安全性 → 屏幕录制 |

> ⚠️ 如果通过「晴天 Util」启动服务，需要给 `晴天 Util.app` 授权（不是终端）。
> 每次重新打包后，macOS 会静默撤销权限，需要在设置中删除后重新添加。
> 晴天 Util 内置「🔧 修复 Mac 权限」按钮可一键跳转。

# QingAgent — 个人 AI 自动化助手

基于本地 Ollama 大模型，通过自然语言在**手机/浏览器**远程控制 Mac 上的应用（微信、浏览器、编辑器等）。

## 快速开始

```bash
cd ~/AIProject/QingAgent

# 激活虚拟环境
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
| `给丸子发微信说晚饭吃啥` | 打开微信，搜索"丸子"，发送消息 |
| `给AG发消息说 帮我检查一下这段代码` | 聚焦 Antigravity 编辑器的 Agent 面板，发送指令 |
| `帮我打开百度搜一下天气` | 打开浏览器，搜索天气 |
| `给晴天Util发消息说 打开日历` | 操作晴天 Util 应用 |

## 支持的别名

| 应用 | 官方名 | 支持别名 |
|------|--------|---------|
| 微信 | 微信 | WeChat、wechat |
| 编辑器 | Antigravity | AG、ag、编辑器、Cursor |
| 浏览器 | 浏览器 | Safari、Chrome、browser |
| 工具 | 晴天Util | QingUtil、工具 |

## 项目结构

```
QingAgent/
├── main.py                     # 主入口（serve / cli / test 三种模式）
├── qingagent/
│   ├── config.py               # 全局配置（模型、端口、延迟参数）
│   ├── planner/
│   │   └── planner.py          # AI Planner（意图解析 → 查找 Skill → 执行）
│   ├── skills/
│   │   ├── __init__.py         # SkillRegistry（注册中心 + 别名查找）
│   │   ├── base.py             # BaseSkill 基类（Intent / 能力描述 / 激活窗口）
│   │   ├── wechat.py           # 微信 Skill
│   │   ├── browser.py          # 浏览器 Skill
│   │   ├── antigravity.py      # Antigravity 编辑器 Skill
│   │   └── qingtian_util.py    # 晴天 Util Skill
│   ├── core/
│   │   ├── window.py           # 窗口查找与激活（CGWindowList + AppleScript）
│   │   ├── actions.py          # 鼠标键盘操作封装（pyautogui）
│   │   ├── vision.py           # AI 视觉识别（Ollama 多模态模型）
│   │   └── verify.py           # 执行结果验证
│   └── server/
│       └── app.py              # HTTP Web 服务（异步任务队列）
├── venv/                       # Python 虚拟环境
└── requirements.txt
```

## 配置说明

编辑 `qingagent/config.py`：

```python
# 意图解析模型（越轻量越快，推荐 qwen2.5:7b）
PLANNER_MODEL = "qwen2.5:7b"

# 视觉识别模型（需要多模态能力，推荐 gemma4:26b）
VISION_MODEL = "gemma4:26b"

# Web 服务端口
SERVER_PORT = 8077
```

## 技术架构

```
用户输入（自然语言）
       ↓
   AI Planner（Ollama 意图解析，~1.5s）
       ↓
   SkillRegistry（别名匹配查找对应 Skill）
       ↓
   Skill.execute()
     ├── window.activate_and_find()  # 激活应用，找窗口坐标
     ├── Cmd+L / 快捷键              # 快速定位输入框（~0.3s）
     └── vision.find_element()      # AI 视觉兜底（~15s）
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
        # 实现逻辑
        ...
```

然后在 `skills/__init__.py` 的 `auto_register()` 中注册。

### macOS 权限要求

| 权限 | 用途 | 授权方式 |
|------|------|---------|
| 辅助功能 | 模拟鼠标/键盘点击 | 系统设置 → 隐私与安全性 → 辅助功能 |
| 屏幕录制 | 截图用于 AI 视觉识别 | 系统设置 → 隐私与安全性 → 屏幕录制 |

> ⚠️ 如果通过「晴天 Util」启动服务，需要给 `晴天 Util.app` 授权（不是终端）。
> 每次重新打包后，macOS 会静默撤销权限，需要在设置中删除后重新添加。

# QingAgent — 个人 AI 自动化助手

基于本机 **MLX 大模型（oMLX）**，通过自然语言在**手机/浏览器**远程控制 Mac 上的应用（微信、浏览器、编辑器等）。支持串行任务队列、截图 HITL 确认、AI 三段视觉精准定位，以及 macOS Accessibility 控件级输入框定位。

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
| `给Codex发消息说 帮我评审这个方案` | 聚焦 Codex 当前会话输入框，粘贴指令并回车发送 |
| `聚焦Codex输入框` | 只验证 Codex 输入框定位，不发送消息 |
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
| 代码助手 | Codex | codex、代码助手 |
| 浏览器 | 浏览器 | Safari、Chrome、browser |
| 工具 | 晴天Util | QingUtil、工具 |

## 核心特性

### 🔒 HITL（人在环路）强制确认与多步断点执行
所有可能会造成物理影响的操作（如微信发送交互）均会挂起阻塞任务进行安全截图和确认流（HITL）。系统引进了本地 Memory 和基于任务栈的多次接续执行能力。如果遇到手动操作阻滞，调度器能妥善将长串流步骤暂存，确保前端回调确权后再精确复原上下文执行后续动作，彻底消除误触并兼顾大型事务组合。

### 📋 串行任务队列
使用 `queue.Queue` 实现线程安全的串行任务调度，防止多条指令并行执行时的鼠标/键盘物理冲突。多个请求会自动排队，UI 实时显示队列状态。

### 👁️ 三段显微精准视觉定位与全局工程认知
- 机器视觉底层采用 oMLX 三步递进缩放（`全屏 → 局部300px → 局部80px对中`），强力解决 AI 漂移。
- `CodeQuerySkill` 结合 `project_registry.py` 项目知识库注册表，让 Agent 具备跨文件源码检索与项目目录级知识获取能力。`project_registry.py` 是数据源，不是独立运行时 Skill。

### 🎯 macOS Accessibility 控件级定位
- `BaseSkill` 内置 `find_text_input_by_accessibility()` / `click_text_input_by_accessibility()`，可通过系统无障碍树识别 `AXTextArea`、`AXTextField` 等真实文本输入控件。
- 这类定位不依赖截图像素、固定坐标或屏幕分辨率，适合 Codex / Antigravity 这类会在主屏、副屏之间移动的桌面应用。
- 视觉识别仍作为兜底：当应用没有暴露无障碍控件时，再根据 hint 文案和周边 UI 描述进行定位。

### 🤝 多 Agent 群聊协作
- `qingagent.group_chat` 是可追踪协作流：Agent 的正式回复写入本地 JSONL，QingAgent 只转发“最新待处理消息”，避免截图/OCR 抓回复。
- 支持 `development` / `debate` / `chat` 三种模式：开发模式沉淀方案、实现、评审和最终结论；辩论模式强调短回合攻防；闲聊模式用于轻量讨论。
- 开发模式使用共享工作区文档：`brief.md` 固定目标，`proposal.md` 存当前方案，`implementation.md` 存实现记录，`review.md` 存当前评审，`decision.md` 存最终结论，`changelog.md` 追加每轮摘要。
- 支持 blocked 用户介入和续接：用户决策会写回 `brief.md`，再作为上一位 AI 给下一位 AI 的续接消息，不把用户变成第三个长期 Agent。
- 角色模板支持产品探索、需求定稿、实现执行、辩论、复盘等场景，可按任务选择并微调。

### 🧪 自动化测试验证（以 QingOA 为例）
- QingOA 是第一个接入 QingAgent 自动化能力的全栈验证项目。
- 业务规则、自动化 case 和 debug 断言语义在 `/Users/konglingjia/AIProject/QingOaFullStack/.agents/` 中维护。
- QingAgent 提供通用执行能力（ADB / WAP / API / case runner / 报告），不保存 QingOA 业务细节。

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
│   │   ├── base.py             # BaseSkill 基类（Intent / 激活窗口 / 视觉点击 / AX 输入框定位）
│   │   ├── wechat.py           # 微信 Skill（含 HITL 截图确认）
│   │   ├── browser.py          # 浏览器 Skill
│   │   ├── antigravity.py      # Antigravity 编辑器 Skill
│   │   ├── codex.py            # Codex 桌面端 Skill（聚焦输入框 / 发送消息）
│   │   ├── qingtian_util.py    # 晴天 Util Skill
│   │   ├── os_control.py       # 系统截图 Skill（QQ截图 / 窗口吸附）
│   │   ├── code_query.py       # 代码检索与查阅
│   │   ├── project_registry.py # CodeQuerySkill 的项目知识库注册表（非 Skill）
│   │   └── task_monitor.py     # 多步骤任务审计追踪机制
│   ├── core/
│   │   ├── window.py           # 窗口查找与激活（CGWindowList + AppleScript）
│   │   ├── actions.py          # 鼠标键盘操作封装（pyautogui）
│   │   ├── vision.py           # AI 视觉识别（三段显微精准定位，oMLX 多模态）
│   │   └── verify.py           # 执行结果验证
│   ├── group_chat/             # 多 Agent 本地 JSONL 协作流
│   └── server/
│       └── app.py              # HTTP Web 服务（任务队列 + HITL UI）
├── .agents/
│   └── skills/                 # 面向未来 AI 的 QingAgent 平台知识 Skill
├── venv/                       # Python 虚拟环境
└── requirements.txt
```

## AI 入口地图

未来 AI 进入 QingAgent 项目时，按任务类型先读对应文档：

| 任务类型 | 先读 |
|---|---|
| 理解项目整体、改运行时 Skill、改 Planner / HITL | `.agents/skills/qingagent-guide/SKILL.md` |
| 改多 Agent 群聊、relay、role templates、blocked 续接 | `.agents/skills/qingagent-group-chat/SKILL.md` |
| 改 Web UI 风格、按钮、卡片、页面密度 | `.agents/skills/qingagent-ui-style/SKILL.md` |
| 改测试台、benchmark、模型验证、视觉测试页面 | `.agents/skills/qingagent-testbench/SKILL.md` |
| QingOA 打卡/请假/WAP 自动化 | `/Users/konglingjia/AIProject/QingOaFullStack/.agents/skills/` |

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
    ├── Accessibility AXTextArea   # 控件级定位文本输入框
    ├── Cmd+L / 快捷键              # 应用有快捷键时快速定位输入框
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

### 复用输入框定位底座

对聊天框、搜索框、命令输入框等文本输入场景，优先复用 `BaseSkill` 的无障碍定位：

```python
ok = self.click_text_input_by_accessibility(
    search_rect=self._window_rect,
    placeholder_keywords=("请输入", "搜索"),
    label="目标输入框",
)
```

如果目标 App 是 Electron / WebView / 原生 macOS 控件，并且暴露了 `AXTextArea` 或 `AXTextField`，这会比截图识别和固定坐标稳定得多。若未命中，再用 `find_and_click()` 走视觉兜底。

### 运行多 Agent 群聊

直接打开 Web 控制台：

```bash
python main.py serve
```

然后访问 `http://127.0.0.1:8077/group-chat`。

也可以用 CLI 调试会话：

```bash
python -m qingagent.group_chat init --session demo-session
```

把第一条任务发给 Codex：

```bash
python -m qingagent.group_chat start --session demo-session --target codex
```

Codex 收到任务后，会被要求用下面这种方式写入 outbox：

```bash
python -m qingagent.group_chat append \
  --session demo-session \
  --from codex \
  --to antigravity \
  --round 1 \
  --type proposal <<'EOF'
这里是 Codex 的方案正文
EOF
```

启动转发器，把待处理消息转给目标 Agent：

```bash
python -m qingagent.group_chat relay --session demo-session --watch --interval 3
```

开发模式里的工作文档可以单独写入：

```bash
python -m qingagent.group_chat doc \
  --session demo-session \
  --file implementation.md <<'EOF'
# Implementation

changed_files:
- qingagent/...

summary:
- 完成某个实现点。

verification:
- python -m py_compile ...
EOF
```

调试时可以先不真的操作桌面，只打印将要发送的内容：

```bash
python -m qingagent.group_chat start --dry-run
python -m qingagent.group_chat relay --once --dry-run
```

开发模式会围绕 `brief.md`、`proposal.md`、`implementation.md`、`review.md`、`decision.md` 和 `changelog.md` 推进；辩论模式不使用 review 状态头，按短回合与最大轮次收敛。

### macOS 权限要求

| 权限 | 用途 | 授权方式 |
|------|------|---------|
| 辅助功能 | 模拟鼠标/键盘点击；读取 macOS Accessibility 控件树定位输入框 | 系统设置 → 隐私与安全性 → 辅助功能 |
| 屏幕录制 | 截图用于 AI 视觉识别 | 系统设置 → 隐私与安全性 → 屏幕录制 |

> ⚠️ 如果通过「晴天 Util」启动服务，需要给 `晴天 Util.app` 授权（不是终端）。
> 每次重新打包后，macOS 会静默撤销权限，需要在设置中删除后重新添加。
> 晴天 Util 内置「🔧 修复 Mac 权限」按钮可一键跳转。

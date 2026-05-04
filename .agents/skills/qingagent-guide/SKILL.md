---
name: QingAgent 自动化助手开发指南
description: QingAgent 的项目入口、运行时 Skill、AI 知识 Skill、Planner、HITL、桌面控制和常见验证规则。新增或修改 QingAgent 核心能力前必读。
---

# QingAgent 开发指南

## 先判断你在改哪一层

QingAgent 现在有三层不同含义的“Skill / 知识资产”，不要混用：

| 层级 | 路径 | 作用 | 修改原则 |
|---|---|---|---|
| 运行时 Skill | `qingagent/skills/*.py` | Planner / relay 真正调用的可执行能力 | 改行为、补 intent、接 App 时才改 |
| Agent 知识 Skill | `.agents/skills/*/SKILL.md` | 给未来 AI 读的项目规则和工作流 | 沉淀稳定规则，不写一次性聊天记录 |

如果只是让未来 AI 更懂项目，优先改 `.agents/skills/*/SKILL.md` 和 README；不要把业务知识塞进运行时 Skill。

## 项目路径

| 资源 | 路径 |
|---|---|
| 源码根目录 | `/Users/konglingjia/AIProject/QingAgent/` |
| Web 入口 | `python main.py serve`，默认端口 `8077` |
| 运行时 Skill | `qingagent/skills/` |
| Web 服务 | `qingagent/server/app.py` |
| 群聊模块 | `qingagent/group_chat/` |
| Agent 知识 Skill | `.agents/skills/` |
| QingOA 被测项目 | `/Users/konglingjia/AIProject/QingOaFullStack/` |

## 当前已注册的运行时 Skill

以 `qingagent/skills/__init__.py` 的 `SkillRegistry.auto_register()` 为准：

| Skill | app_name | 主要用途 |
|---|---|---|
| `WeChatSkill` | 微信 | 微信文本/图片/文件发送，强制 HITL 确认 |
| `BrowserSkill` | 浏览器 | 打开 URL、搜索、浏览器小游戏 |
| `AntigravitySkill` | Antigravity | 聚焦 AG Agent 面板并发送消息 |
| `CodexSkill` | Codex | 通过 macOS AXTextArea 精准聚焦 Codex 输入框并发送消息 |
| `QingTianUtilSkill` | 晴天Util | 操作晴天 Util 的功能 Tab、日历、项目服务等 |
| `OSControlSkill` | System | QQ 截图、自定义区域截图、窗口吸附截图 |
| `MinesweeperSkill` | Minesweeper | 扫雷游戏 UI 自动化实验 |
| `TaskMonitorSkill` | Task | 长任务暂停、恢复和审计追踪 |
| `CodeQuerySkill` | Code | 代码检索、读文件片段、项目结构查询 |

`qingagent/skills/project_registry.py` **不是 Skill**。它是 `PROJECTS` 字典和 `find_project` / `list_projects` 函数，是 `CodeQuerySkill` 的项目知识库注册表数据源；不要把它注册进 `SkillRegistry`。

## 新增运行时 Skill 的规则

1. 继承 `BaseSkill`。
2. 定义 `app_name` / `app_aliases` / `app_context`。
3. 在 `register_intents()` 里添加 `Intent`。
4. 实现 `execute_<intent_name>(self, slots)`。
5. 在 `SkillRegistry.auto_register()` 中注册。
6. 若触碰真实鼠标/键盘或发消息，必须考虑 HITL 或可恢复失败。

最小模板：

```python
class MySkill(BaseSkill):
    app_name = "MyApp"
    app_aliases = ["MyApp", "我的应用"]
    app_context = "MyApp 应用界面截图"

    def register_intents(self):
        self.add_intent(Intent(
            name="send_prompt",
            description="给 MyApp 发送提示词",
            required_slots=["message"],
            examples=["给MyApp发消息说 检查这个方案"],
        ))

    def execute_send_prompt(self, slots: dict) -> dict:
        if not self.activate():
            return {"success": False, "message": "无法激活应用", "data": None}
        return {"success": True, "message": "完成", "data": None}
```

## 输入框定位优先级

对 Codex / Antigravity / 浏览器输入框这类目标，优先顺序是：

1. 应用快捷键：如 `Cmd+L`、固定命令面板快捷键。
2. macOS Accessibility：`AXTextArea` / `AXTextField`。
3. 视觉识别：根据 hint 文案、周边 UI 和截图定位。
4. 坐标兜底：仅用于稳定控件或临时调试。

`BaseSkill.find_text_input_by_accessibility()` 和 `click_text_input_by_accessibility()` 是跨屏幕、跨分辨率更稳定的方案。Codex 输入框定位已经验证过 AXTextArea 方案比像素坐标可靠。

## BaseSkill 截图规则

`BaseSkill.screenshot()` 当前是 **精确截取当前应用窗口矩形**，不会向四周外扩 PAD。

如果弹窗、菜单、权限确认框不在当前窗口矩形内，不要假设 screenshot 会自动捕获。应先：

1. 识别当前焦点窗口或系统弹窗。
2. 切换到对应窗口矩形。
3. 再截图或使用系统 UI 自动化处理。

`_last_screenshot_rect` 保存的是最近一次截图使用的矩形，坐标换算必须基于它：

```python
target_rect = getattr(self, "_last_screenshot_rect", self._window_rect)
actions.click_at_normalized(target_rect, coords)
```

## HITL 与队列

QingAgent 的物理操作由 `server/app.py` 的串行任务队列执行。同一时间只应该有一个 Skill 操作鼠标和键盘。

微信发送、文件选择、敏感操作等会触发 HITL：

1. Skill 截图并调用服务端确认。
2. Web UI 展示截图和确认按钮。
3. 用户确认后任务继续。
4. 用户取消或超时则任务失败并释放队列。

改 HITL 相关代码时，要确认前端状态、任务线程、恢复路径三者一致。

## 多 Agent 群聊相关任务

涉及下面关键词时，先读 `.agents/skills/qingagent-group-chat/SKILL.md`：

- `group_chat`
- 多 Agent 群聊
- Codex / Antigravity relay
- role templates
- `brief.md` / `proposal.md` / `review.md`
- blocked / needs_user_decision / sign_off / forwarded
- 辩论模式 / 开发模式 / 闲聊模式

群聊不是普通聊天页面，而是可追踪协作流。不要把用户介入消息当成第三个长期 Agent；用户决策应该补入 `brief.md`，再作为上一轮 AI 对 AI 的续接消息转回链路。

## 测试台和模型验证相关任务

涉及 benchmark、测试台、视觉模型、模型能力比较、Web Tab UI 时，先读 `.agents/skills/qingagent-testbench/SKILL.md`。

这类任务通常要同时考虑：

- Web UI 交互是否清晰。
- 模型调用和本地服务是否可用。
- 是否能保存可复查的测试报告或截图。

## 外部项目自动化边界

QingAgent 是自动化平台，不保存外部被测项目的业务细节。涉及 QingOA 打卡、请假、WAP 或 workflow 自动化时，先切到 QingOA 项目资产：

| 资源 | 路径 |
|---|---|
| QingOA 项目根目录 | `/Users/konglingjia/AIProject/QingOaFullStack/` |
| QingOA 自动化 Skill | `/Users/konglingjia/AIProject/QingOaFullStack/.agents/skills/` |
| QingOA 自动化 Case | `/Users/konglingjia/AIProject/QingOaFullStack/.agents/cases/` |
| QingOA 版本设计文档 | `/Users/konglingjia/AIProject/AI 文档/qingoa/` |

QingAgent 侧只维护 ADB / WAP / API / case runner / 报告生成等通用执行能力。新增第二个被测项目前，不在 QingAgent 内抽象通用 adapter 协议，也不把被测项目业务规则写回 QingAgent 的 Agent 知识 Skill。

## 常用验证命令

```bash
cd /Users/konglingjia/AIProject/QingAgent
./venv/bin/python -m compileall qingagent
./venv/bin/python -m qingagent.group_chat --help
```

如果改了 Web UI，启动服务后打开：

```bash
python main.py serve
# http://127.0.0.1:8077
```

如果改了外部项目自动化脚本，进入对应项目仓库运行其验证命令；QingAgent 仓库只验证平台代码。

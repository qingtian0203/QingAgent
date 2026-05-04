---
name: QingAgent 多 Agent 群聊协作
description: QingAgent group_chat 开发、辩论、闲聊模式的协作协议、relay 转发、工作文档、用户介入和故障恢复指南。修改 /group-chat UI、role templates、prompts、relay 或会话状态前必读。
---

# QingAgent 多 Agent 群聊协作

## 定位

多 Agent 群聊不是普通聊天记录页，而是把多个 AI 的产物、评审、用户决策和最终结论沉淀到本地文件的协作流。

核心目标：

- 减少 UI 截图/OCR 抓回复的不稳定。
- 让 Agent 只读必要上下文，不反复消耗完整聊天历史。
- 把关键产物沉淀为 `brief.md`、`proposal.md`、`implementation.md`、`review.md`、`decision.md`、`changelog.md`。
- 用户只在阻塞点介入，介入后能续接回原来的 AI 对 AI 链路。

## 关键路径

| 文件 | 作用 |
|---|---|
| `qingagent/group_chat/store.py` | 会话目录、JSONL 消息、工作文档读写 |
| `qingagent/group_chat/prompts.py` | development / debate / chat 提示词生成 |
| `qingagent/group_chat/relay.py` | 待转发消息扫描、目标 Agent 发送、用户介入处理 |
| `qingagent/server/app.py` | `/group-chat` 页面和 API |
| `runtime/group_chat/<session>/messages.jsonl` | 当前会话消息流水 |
| `runtime/group_chat/<session>/workspace/*.md` | 当前会话工作文档 |

## 三种模式

| 模式 | 用途 | 关键规则 |
|---|---|---|
| `development` | 方案、实现、评审、修复、最终交付 | 必须使用工作文档；只有 blocked/final 发给用户 |
| `debate` | 短回合辩论 | 不写 review 状态头；每轮只打一个点；通常靠最大轮次结束 |
| `chat` | 轻量讨论或创意探索 | 不强制 proposal/review 状态机 |

不要把 `debate` 和 `chat` 跑成 `development`。否则 relay 会等待不存在的 `review.md` 状态，流程会空转。

## Development 工作文档职责

| 文档 | 写入规则 |
|---|---|
| `brief.md` | 固定目标和用户补充约束；除非用户追加决策，否则不要覆盖 |
| `proposal.md` | 当前最新版方案；可覆盖 |
| `implementation.md` | 当前实现记录；Codex 完成改动后覆盖 |
| `review.md` | 当前最新版评审意见；Antigravity 覆盖 |
| `decision.md` | 最终结论；收敛时写 |
| `changelog.md` | 每轮关键变更；只追加 |

`review.md` 顶部必须保留机器可读状态头：

```text
phase: planning | implementation | review | fix | blocked | final
status: needs_changes | approved | blocked
blocking_count: 0
sign_off: false
needs_user_decision: false
```

## 用户介入规则

用户不是第三个长期 Agent。阻塞时：

1. AI 写 `status: blocked` 或发 `to=user` 的 blocked 消息。
2. UI 展示“需要用户介入”。
3. 用户提交决策后，系统把决策追加到 `brief.md`。
4. 续接消息应作为“上一位 AI -> 下一位 AI”的续接，不应把用户加入主对话链路。

如果用户介入后仍显示 blocked，优先检查：

- 最新 blocked 消息是否已被消费。
- `review.md` 顶部是否仍是 `status: blocked` 或 `needs_user_decision: true`。
- relay 是否把用户决策发给了正确目标。

## 标签语义

| 字段 | UI 建议文案 | 含义 |
|---|---|---|
| `round` | `第 N 轮` | 当前消息轮次 |
| `type=proposal` | `方案` | 当前轮方案 |
| `type=implementation` | `实现` | 当前轮实现记录 |
| `type=review` | `评审` | 当前轮评审 |
| `type=blocked` | `需介入` | 需要用户拍板 |
| `type=final` + `done=true` | `最终完成` | 本会话收敛 |
| `forwarded=true` | `已转发` | relay 已把消息发给目标 Agent |

`重新发送给对方` 只用于故障恢复：当消息写入 JSONL 但目标 Agent 没收到，或转发被 UI 权限/窗口阻塞打断时使用。正常流程不要反复点击。

## 角色模板

角色模板配置在 `AI 文档/qingagent/role_templates.json` 和前端会话配置中使用。每个模板必须明确：

- `mode`: `development` / `chat` / `debate`
- `role_a`
- `role_b`
- 适用场景
- 输出期望

角色模板是启动配置，不是运行中强约束；如果任务变了，应新建会话或明确更新 brief。

## 修改后验证

```bash
cd /Users/konglingjia/AIProject/QingAgent
./venv/bin/python -m compileall qingagent
./venv/bin/python -m qingagent.group_chat --help
./venv/bin/python -m qingagent.group_chat relay --once --dry-run
```

如果改了 `/group-chat` 页面，启动 `python main.py serve` 后用浏览器验证：

- 新建会话
- 选择角色模板
- 发起首轮
- blocked 用户介入
- 重新发送给对方
- final/done 结束态

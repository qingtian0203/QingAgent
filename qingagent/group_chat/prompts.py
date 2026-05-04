from __future__ import annotations

from .store import (
    DEFAULT_AGENTS,
    DEFAULT_SESSION,
    DEFAULT_TOPIC,
    REPO_ROOT,
    load_meta,
    load_workspace,
    recent_transcript,
)


def role_text(session: str, agent: str) -> str:
    meta = load_meta(session)
    agents = meta.get("agents") or DEFAULT_AGENTS
    return agents.get(agent) or DEFAULT_AGENTS.get(agent) or agent


def append_command(
    session: str,
    from_agent: str,
    to_agent: str,
    round_no: int,
    msg_type: str = "reply",
    done: bool = False,
) -> str:
    done_flag = " --done" if done else ""
    return (
        f"cd {REPO_ROOT} && ./venv/bin/python -m qingagent.group_chat append "
        f"--session {session} --from {from_agent} --to {to_agent} "
        f"--round {round_no} --type {msg_type}{done_flag} <<'EOF'\n"
        "在这里写你的完整回复正文\n"
        "EOF"
    )


def doc_command(session: str, file_name: str, append: bool = False) -> str:
    append_flag = " --append" if append else ""
    return (
        f"cd {REPO_ROOT} && ./venv/bin/python -m qingagent.group_chat doc "
        f"--session {session} --file {file_name}{append_flag} <<'EOF'\n"
        "在这里写 Markdown 正文\n"
        "EOF"
    )


def workspace_prompt_block(session: str) -> str:
    workspace = load_workspace(session)
    if not workspace.get("enabled"):
        return ""
    lines = ["本会话启用了开发模式，工作文档如下："]
    for item in workspace.get("files", []):
        lines.append(f"- {item['name']}: {item['path']}")
    lines.append("")
    lines.append("文档职责：")
    lines.append("- brief.md：固定目标和约束，除非用户补充要求，否则不要覆盖。")
    lines.append("- proposal.md：当前最新版方案，每次修订可以覆盖。")
    lines.append("- implementation.md：当前实现记录，Codex 完成代码改动后覆盖写入，供评审使用。")
    lines.append("- review.md：当前最新版评审意见，每次评审可以覆盖。")
    lines.append("- decision.md：最终结论，只有收敛时写入。")
    lines.append("- changelog.md：每轮关键变更，只追加，不覆盖。")
    lines.append("")
    lines.append("开发阶段：")
    lines.append("- planning：写 proposal.md，等待方案评审。")
    lines.append("- implementation：Codex 实际改代码，写 implementation.md。")
    lines.append("- review：Antigravity 基于 implementation.md、git diff、测试结果做代码评审。")
    lines.append("- fix：Codex 根据 review.md 修复，再回到 review。")
    lines.append("- blocked：任一 AI 发现必须用户拍板的问题，暂停等待用户。")
    lines.append("- final：写 decision.md 并用 --done 结束。")
    lines.append("")
    lines.append("review.md 顶部必须包含机器可读状态头：")
    lines.append("phase: planning | implementation | review | fix | blocked | final")
    lines.append("status: needs_changes | approved | blocked")
    lines.append("blocking_count: 当前仍阻塞、必须用户决策的问题数量")
    lines.append("sign_off: true | false")
    lines.append("needs_user_decision: true | false")
    lines.append("")
    lines.append("blocking_count 只统计当前仍无法由 AI 自行判断的问题，不累计历史问题；任一 AI 发现必须用户拍板的问题即可写 blocked，不需要双方同时认定。")
    return "\n".join(lines)


def initial_prompt(
    session: str = DEFAULT_SESSION,
    topic: str = DEFAULT_TOPIC,
    target_agent: str = "codex",
) -> str:
    meta = load_meta(session)
    topic = meta.get("topic") or topic
    other = "antigravity" if target_agent == "codex" else "codex"
    workspace_block = workspace_prompt_block(session)
    max_rounds = int(meta.get("max_rounds") or 8)
    if meta.get("mode") == "development":
        return f"""你正在参与 QingAgent 多 AI 协作群聊：开发模式。

会话 ID：{session}
讨论目标：{topic}
你的身份：{role_text(session, target_agent)}

{workspace_block}

本模式的关键规则：
1. 不要只在聊天窗口直接回复正文。
2. 你必须先围绕工作文档产出内容，再写入本地 JSONL 消息文件。
3. 写入 JSONL 后，聊天窗口只输出一行确认，例如：[已写入 outbox: msg_id=xxx]
4. 每轮只写一次 outbox，不要自由发散太久。
5. 如果你认为已经形成最终方案，用 --type final --done --to user，并先写入 decision.md。
6. 如果出现无法自行判断、继续会瞎猜的问题，写 status: blocked 的 review.md，让中控暂停等待用户介入。

第一轮任务：
1. 读取 brief.md，理解固定目标、边界和角色。
2. 覆盖写入 proposal.md，给出当前最新版初始方案。
3. 追加 changelog.md，记录本轮你写了什么。
4. 写一条简短 outbox 发给 {other}，说明 proposal.md 已生成，请对方评审。

写 proposal.md：

```bash
{doc_command(session, "proposal.md")}
```

追加 changelog.md：

```bash
{doc_command(session, "changelog.md", append=True)}
```

发给 {other} 的 outbox：

```bash
{append_command(session, target_agent, other, 1, "proposal")}
```
"""
    if meta.get("mode") == "debate":
        return f"""你正在参与 QingAgent 多 AI 协作群聊：辩论模式。

会话 ID：{session}
辩题：{topic}
你的身份：{role_text(session, target_agent)}

本模式的关键规则：
1. 不要只在聊天窗口直接回复正文，正式发言必须写入本地 JSONL 消息文件。
2. 写入后，聊天窗口只输出一行确认，例如：[已写入 outbox: msg_id=xxx]
3. 这是辩论赛式短回合攻防，不是项目方案评审；不要写 proposal/review 状态头。
4. 每轮只打一个核心点，正文控制在 180-320 字，最多 3 个短段或 3 个要点。
5. 必须针锋相对地回应对方上一轮，不要每轮重写完整长文。
6. 每轮结尾只抛 1 个尖锐追问，逼对方回答关键矛盾。
7. 最大轮次为 {max_rounds}。未到最后一轮时不要 --done，不要把结论提前交给用户。

第一轮任务：
- 用一句话亮明立场。
- 给出 1-2 个最强论据。
- 向 {other} 抛出 1 个必须正面回答的问题。

写入命令：

```bash
{append_command(session, target_agent, other, 1, "reply")}
```
"""
    return f"""你正在参与 QingAgent 多 AI 协作群聊。

会话 ID：{session}
讨论目标：{topic}
你的身份：{role_text(session, target_agent)}

本模式的关键规则：
1. 你不能只在聊天窗口直接回复正文。
2. 你的正式回复必须写入本地 JSONL 消息文件。
3. 写入后，聊天窗口只输出一行确认，例如：[已写入 outbox: msg_id=xxx]
4. 每轮只写一次 outbox，不要自由发散太久。
5. 如果你认为讨论已经形成最终方案，用 --type final --done --to user 写最终结论。

请先给出第一轮方案，发给 {other} 评审。写入命令如下：

```bash
{append_command(session, target_agent, other, 1, "proposal")}
```

第一轮建议重点：
- 先明确目标拆解和边界
- 给出你角色视角下的核心方案
- 明确需要对方评审的问题
- 如果涉及实现，请说明接口、交互、测试和风险
"""


def forward_prompt(message: dict) -> str:
    session = message["session"]
    meta = load_meta(session)
    topic = meta.get("topic") or DEFAULT_TOPIC
    max_rounds = int(meta.get("max_rounds") or 8)
    target = message["to"]
    sender = message["from"]
    reviewer = "antigravity" if target == "codex" else "codex"
    next_round = int(message.get("round") or 0) + 1
    reply_type = "reply"
    if meta.get("mode") == "development":
        reply_type = "review" if target == "antigravity" else "reply"
    workspace_block = workspace_prompt_block(session)

    if meta.get("mode") == "development":
        if target == "antigravity":
            action = f"""本轮任务：
1. 读取 brief.md、proposal.md、implementation.md；如果 implementation.md 已记录代码改动，还要查看当前 git diff 和测试结果。
2. 覆盖写入 review.md：只保留当前仍然有效的问题、疑义和建议；已解决的旧问题不要继续写入。
3. 追加 changelog.md，记录本轮评审结论。
4. 如果 implementation.md 仍是占位或没有实际改动记录，本轮是“方案评审”：
   - 方案可执行但还未实现：写 phase: implementation，status: approved，sign_off: false。
   - 方案还需修改：写 phase: planning，status: needs_changes，sign_off: false。
5. 如果 implementation.md 已有实现记录，本轮是“代码评审”：
   - 代码仍需修复：写 phase: fix，status: needs_changes，sign_off: false。
   - 代码可以验收：写 phase: final，status: approved，sign_off: true。
6. 如果必须用户拍板才能继续，写 phase: blocked，status: blocked，needs_user_decision: true，blocking_count 为当前阻塞问题数量，并在 review.md 里列出需要用户回答的问题；随后写 outbox 给 user，说明需要用户介入。

写 review.md：

```bash
{doc_command(session, "review.md")}
```

追加 changelog.md：

```bash
{doc_command(session, "changelog.md", append=True)}
```

继续发给 {sender}：

```bash
{append_command(session, target, sender, next_round, reply_type)}
```

需要用户介入时发给 user：

```bash
{append_command(session, target, "user", next_round, "blocked")}
```
"""
        else:
            action = f"""本轮任务：
1. 读取 brief.md、proposal.md、implementation.md、review.md。
2. 先检查 review.md 顶部状态：如果 phase: blocked、status: blocked 或 needs_user_decision: true，不要猜测，写 outbox 给 user 请求介入。
3. 如果 phase: final 或 review.md 是 status: approved 且 sign_off: true，先写 decision.md，再使用 --type final --done --to user。
4. 如果 phase: implementation，或者 review.md 是 status: approved 但 sign_off: false，说明方案已过审：现在实际修改代码，完成后覆盖 implementation.md，写明 changed_files、summary、verification、risks，然后发给 {reviewer} 代码评审。
5. 如果 phase: planning 且 status: needs_changes，优先覆盖更新 proposal.md，说明采纳了哪些评审；然后发给 {reviewer} 复审。
6. 如果 phase: fix 或已有 implementation.md 实现记录且 status: needs_changes，实际修复代码，覆盖 implementation.md，并发给 {reviewer} 复审。
7. 追加 changelog.md，记录本轮是方案修订、代码实现、代码修复还是最终收敛。
8. 只有 blocked 和 final 发给 user；方案修订、实现完成、修复完成都必须发给评审 Agent。

更新 proposal.md：

```bash
{doc_command(session, "proposal.md")}
```

追加 changelog.md：

```bash
{doc_command(session, "changelog.md", append=True)}
```

写 implementation.md（完成代码实现或修复后使用）：

```bash
{doc_command(session, "implementation.md")}
```

继续发给 {reviewer}：

```bash
{append_command(session, target, reviewer, next_round, reply_type)}
```

完成实现后发给 {reviewer} 做代码评审：

```bash
{append_command(session, target, reviewer, next_round, "implementation")}
```

需要用户介入时发给 user：

```bash
{append_command(session, target, "user", next_round, "blocked")}
```
"""

        return f"""你正在参与 QingAgent 多 AI 协作群聊：开发模式。

会话 ID：{session}
讨论目标：{topic}
你的身份：{role_text(session, target)}

{workspace_block}

下面是 {sender} 发给你的最新消息：

---
{message.get('body', '').strip()}
---

最近消息摘要：

{recent_transcript(session, limit=2)}

你的通用规则：
1. 以工作文档为准，不要围绕聊天记录无限发散。
2. 当前有效产物覆盖写入，历史过程只追加到 changelog.md。
3. 如果当前轮次已接近最大轮次 {max_rounds}，优先生成 decision.md 并结束。
4. 正式回复必须写入 outbox；写入后聊天窗口只输出一行确认。

{action}
如果你判断可以结束，使用：

```bash
{doc_command(session, "decision.md")}
```

```bash
{append_command(session, target, "user", next_round, "final", done=True)}
```
"""

    if meta.get("mode") == "debate":
        if next_round >= max_rounds:
            end_rule = f"""这一轮已到最大轮次 {max_rounds}，请收束给用户。不要继续发给 {sender}。
最终内容控制在 300-500 字，包括：你的胜负判断、双方最强点、真正分歧、给用户的裁决建议。"""
            command_block = f"""最终发给 user：

```bash
{append_command(session, target, "user", next_round, "final", done=True)}
```"""
        else:
            end_rule = f"""当前是第 {next_round} 轮，尚未到最大轮次 {max_rounds}。禁止 --done，禁止提前交给用户；继续短回合反击并发给 {sender}。"""
            command_block = f"""继续发给 {sender}：

```bash
{append_command(session, target, sender, next_round, "reply")}
```"""
        return f"""你正在参与 QingAgent 多 AI 协作群聊：辩论模式。

会话 ID：{session}
辩题：{topic}
你的身份：{role_text(session, target)}

下面是 {sender} 发给你的最新发言：

---
{message.get('body', '').strip()}
---

最近上下文：

{recent_transcript(session, limit=4)}

辩论回合规则：
1. 只抓对方上一轮最关键的一点反击，不要重新写一篇完整文章。
2. 正文控制在 180-320 字，最多 3 个短段或 3 个要点。
3. 可以承认局部事实，但必须把它转化为己方立场的论据。
4. 不要泛泛总结，不要温和折中；保持明确立场和攻击性。
5. 结尾只问 1 个尖锐问题，让对方下一轮必须回应。
6. 正式回复必须写入 outbox；写入后聊天窗口只输出一行确认。

{end_rule}

{command_block}
"""

    return f"""你正在参与 QingAgent 多 AI 协作群聊。

会话 ID：{session}
讨论目标：{topic}
你的身份：{role_text(session, target)}

下面是 {sender} 发给你的最新消息：

---
{message.get('body', '').strip()}
---

最近上下文：

{recent_transcript(session)}

你的任务：
1. 只基于当前目标继续推进，不要改话题。
2. 如果对方方案有问题，直接指出并给替代方案。
3. 如果已经足够收敛，或当前轮次已接近最大轮次 {max_rounds}，请写最终方案，使用 --type final --done --to user。
4. 正式回复必须写入 outbox；写入后聊天窗口只输出一行确认。

继续回复给 {sender} 的命令：

```bash
{append_command(session, target, sender, next_round, reply_type)}
```

如果你判断可以结束，使用：

```bash
{append_command(session, target, "user", next_round, "final", done=True)}
```
"""

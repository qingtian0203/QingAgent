from __future__ import annotations

import time

from qingagent.skills import SkillRegistry

from .prompts import forward_prompt, initial_prompt
from .store import (
    DEFAULT_SESSION,
    DEFAULT_TOPIC,
    ensure_session,
    load_state,
    get_awaiting_outbox,
    mark_awaiting_outbox,
    mark_done,
    mark_forwarded,
    mark_blocked,
    pending_messages,
    parse_workspace_status,
)


def send_to_agent(agent: str, prompt: str, dry_run: bool = False) -> bool:
    if dry_run:
        print(f"\n--- DRY RUN -> {agent} ---\n{prompt}\n--- END ---")
        return True

    registry = SkillRegistry()
    registry.auto_register()
    skill = registry.get_skill_by_name(agent)
    if not skill:
        print(f"❌ 找不到目标 Agent Skill：{agent}")
        return False
    result = skill.execute("send_prompt", {"prompt": prompt})
    print(result.get("message"))
    return bool(result.get("success"))


def opposite_agent(agent: str | None) -> str:
    text = (agent or "").strip().lower()
    if text == "codex":
        return "antigravity"
    if text == "antigravity":
        return "codex"
    return ""


def next_round(message: dict) -> int:
    try:
        return int(message.get("round") or 0) + 1
    except (TypeError, ValueError):
        return 1


def relay_once(session: str = DEFAULT_SESSION, dry_run: bool = False, max_forwards: int = 1) -> int:
    ensure_session(session)
    workspace_status = parse_workspace_status(session)
    is_blocked = (
        workspace_status.get("needs_user_decision")
        or workspace_status.get("status") == "blocked"
        or workspace_status.get("phase") == "blocked"
    )
    if is_blocked:
        print("🧭 检测到阻塞状态，暂停等待用户介入")
        if not dry_run:
            mark_blocked(session, None, "workspace review blocked")
        return 0

    messages = pending_messages(session)
    if not messages:
        awaiting = get_awaiting_outbox(session)
        if awaiting:
            print(
                f"⏳ 等待 {awaiting.get('from')} 写入 outbox，"
                f"已等 {awaiting.get('elapsed_seconds', 0)} 秒"
            )
        else:
            print("📭 暂无待转发消息")
        return 0

    count = 0
    for message in messages:
        if message.get("done"):
            print(f"🏁 检测到结束消息：{message.get('id')}")
            if not dry_run:
                mark_done(session, message["id"])
            count += 1
            continue

        target = message.get("to")
        if (target or "").strip().lower() == "user":
            print(f"🧭 检测到发给用户的待处理消息：{message.get('id')}")
            if not dry_run:
                mark_blocked(session, message["id"], "agent requested user input")
            count += 1
            continue

        prompt = forward_prompt(message)
        print(f"➡️ 转发 {message.get('id')}：{message.get('from')} -> {target}")
        if send_to_agent(target, prompt, dry_run=dry_run):
            if not dry_run:
                mark_forwarded(session, message["id"])
                mark_awaiting_outbox(
                    session,
                    from_agent=target,
                    to_agent=opposite_agent(target),
                    round_no=next_round(message),
                    msg_type="reply",
                    source_message_id=message["id"],
                    reason="forwarded_to_agent",
                )
            count += 1
        if count >= max_forwards:
            break
    return count


def relay_watch(
    session: str = DEFAULT_SESSION,
    dry_run: bool = False,
    interval: float = 3.0,
    max_total: int = 20,
) -> None:
    ensure_session(session)
    forwarded = 0
    print(f"👀 开始监听群聊会话：{session}")
    print("按 Ctrl+C 停止。")
    while forwarded < max_total:
        state = load_state(session)
        if state.get("done"):
            print("🏁 会话已结束")
            return
        if state.get("blocked"):
            print("🧭 会话已暂停，等待用户介入")
            return
        forwarded += relay_once(session=session, dry_run=dry_run, max_forwards=1)
        state = load_state(session)
        if state.get("done"):
            print("🏁 会话已结束")
            return
        if state.get("blocked"):
            print("🧭 会话已暂停，等待用户介入")
            return
        time.sleep(interval)
    print(f"⏹️ 已达到最大转发次数：{max_total}")


def start_demo(
    session: str = DEFAULT_SESSION,
    topic: str = DEFAULT_TOPIC,
    target_agent: str = "codex",
    dry_run: bool = False,
) -> bool:
    ensure_session(session, topic=topic)
    prompt = initial_prompt(session=session, topic=topic, target_agent=target_agent)
    print(f"🚀 启动群聊：{session} -> {target_agent}")
    ok = send_to_agent(target_agent, prompt, dry_run=dry_run)
    if ok and not dry_run:
        mark_awaiting_outbox(
            session,
            from_agent=target_agent,
            to_agent=opposite_agent(target_agent),
            round_no=1,
            msg_type="reply",
            reason="initial_prompt_sent",
        )
    return ok

from __future__ import annotations

import fcntl
import json
import os
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RUNTIME_DIR = Path(
    os.environ.get("QINGAGENT_GROUP_CHAT_DIR", REPO_ROOT / "runtime" / "group_chat")
)
DEFAULT_SESSION = "qingagent-group-chat-demo"
DEFAULT_TOPIC = "让 Codex 和 Antigravity 讨论一个可落地方案"
DEFAULT_MODE = "development"
DEFAULT_PHASE = "planning"
DEFAULT_AGENTS = {
    "codex": "你是 Codex，角色是顶级工程师和实现负责人。你要给出可落地的接口、App 交互、测试与风险处理方案。",
    "antigravity": "你是 Antigravity，角色是架构评审者和质量守门员。你要从边界、风险、测试、扩展性角度挑问题并补方案。",
}
WORKSPACE_FILE_NAMES = (
    "brief.md",
    "proposal.md",
    "implementation.md",
    "review.md",
    "decision.md",
    "changelog.md",
)


@dataclass(frozen=True)
class SessionPaths:
    root: Path
    messages: Path
    state: Path
    meta: Path
    workspace: Path


def now_iso() -> str:
    return datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(timespec="seconds")


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=ZoneInfo("Asia/Shanghai"))
    return parsed


def elapsed_seconds_since(value: str | None) -> int:
    parsed = parse_iso(value)
    if not parsed:
        return 0
    now = datetime.now(ZoneInfo("Asia/Shanghai"))
    return max(0, int((now - parsed).total_seconds()))


def session_paths(session: str, root: Path | None = None) -> SessionPaths:
    base = (root or DEFAULT_RUNTIME_DIR) / session
    return SessionPaths(
        root=base,
        messages=base / "messages.jsonl",
        state=base / "state.json",
        meta=base / "session.json",
        workspace=base / "workspace",
    )


def ensure_session(
    session: str,
    topic: str = DEFAULT_TOPIC,
    agents: dict | None = None,
    start_target: str = "codex",
    max_rounds: int = 8,
    mode: str = DEFAULT_MODE,
    root: Path | None = None,
) -> SessionPaths:
    paths = session_paths(session, root=root)
    paths.root.mkdir(parents=True, exist_ok=True)
    if not paths.messages.exists():
        paths.messages.touch()
    if not paths.state.exists():
        write_json(
            paths.state,
            {"forwarded_ids": [], "phase": DEFAULT_PHASE, "updated_at": now_iso()},
        )
    if not paths.meta.exists():
        write_json(
            paths.meta,
            {
                "session": session,
                "topic": topic,
                "created_at": now_iso(),
                "mode": normalize_mode(mode),
                "agents": agents or DEFAULT_AGENTS,
                "start_target": normalize_agent(start_target),
                "max_rounds": int(max_rounds),
            },
        )
    meta = read_json(paths.meta, {})
    if meta.get("mode", DEFAULT_MODE) == "development":
        ensure_workspace(session, meta=meta, root=root)
    return paths


def update_session_meta(
    session: str,
    topic: str | None = None,
    agents: dict | None = None,
    start_target: str | None = None,
    max_rounds: int | None = None,
    mode: str | None = None,
) -> dict:
    paths = ensure_session(session, topic=topic or DEFAULT_TOPIC)
    meta = read_json(paths.meta, {})
    meta.setdefault("session", session)
    meta.setdefault("created_at", now_iso())
    meta.setdefault("mode", DEFAULT_MODE)
    if topic is not None:
        meta["topic"] = topic
    if mode is not None:
        meta["mode"] = normalize_mode(mode)
    if agents is not None:
        meta["agents"] = agents
    if start_target is not None:
        meta["start_target"] = normalize_agent(start_target)
    if max_rounds is not None:
        meta["max_rounds"] = int(max_rounds)
    meta["updated_at"] = now_iso()
    write_json(paths.meta, meta)
    if meta.get("mode") == "development":
        ensure_workspace(session, meta=meta)
    return meta


def read_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return default


def write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def load_meta(session: str) -> dict:
    paths = ensure_session(session)
    meta = read_json(paths.meta, {})
    meta.setdefault("mode", DEFAULT_MODE)
    return meta


def workspace_file_path(session: str, file_name: str, root: Path | None = None) -> Path:
    safe_name = normalize_workspace_file(file_name)
    return session_paths(session, root=root).workspace / safe_name


def workspace_paths(session: str, root: Path | None = None) -> dict[str, Path]:
    return {name: workspace_file_path(session, name, root=root) for name in WORKSPACE_FILE_NAMES}


def ensure_workspace(session: str, meta: dict | None = None, root: Path | None = None) -> None:
    paths = session_paths(session, root=root)
    paths.workspace.mkdir(parents=True, exist_ok=True)
    meta = meta or read_json(paths.meta, {})
    meta.setdefault("session", session)
    meta.setdefault("topic", DEFAULT_TOPIC)
    meta.setdefault("agents", DEFAULT_AGENTS)
    meta.setdefault("max_rounds", 8)
    initial_files = {
        "brief.md": render_brief(session, meta),
        "proposal.md": "# Proposal\n\n（等待起始 Agent 写入当前最新版方案。）\n",
        "implementation.md": "# Implementation\n\n（等待执行 Agent 写入本轮实现记录。）\n",
        "review.md": (
            "# Review\n\n"
            "phase: planning\n"
            "status: needs_changes\n"
            "blocking_count: 0\n"
            "sign_off: false\n"
            "needs_user_decision: false\n\n"
            "（等待评审 Agent 写入当前有效问题清单。）\n"
        ),
        "decision.md": "# Decision\n\n（最终收敛后写入结论。）\n",
        "changelog.md": (
            "# Changelog\n\n"
            f"## {now_iso()} 初始化\n"
            "- 创建开发模式工作区。\n"
            "- brief.md 固定目标，proposal.md/implementation.md/review.md/decision.md 保存当前有效产物。\n"
        ),
    }
    for name, content in initial_files.items():
        path = workspace_file_path(session, name, root=root)
        if not path.exists():
            path.write_text(content.rstrip() + "\n", encoding="utf-8")


def render_brief(session: str, meta: dict) -> str:
    agents = meta.get("agents") or DEFAULT_AGENTS
    return f"""# Brief

## 会话

- Session: `{session}`
- Mode: `development`
- Max rounds: `{int(meta.get("max_rounds") or 8)}`

## 固定目标

{meta.get("topic") or DEFAULT_TOPIC}

## 角色

### Codex

{agents.get("codex") or DEFAULT_AGENTS["codex"]}

### Antigravity

{agents.get("antigravity") or DEFAULT_AGENTS["antigravity"]}

## 协作规则

- brief.md 是目标锚点，除非用户补充约束，否则不要改写。
- proposal.md 保存当前最新版方案，每次修订可覆盖。
- implementation.md 保存当前实现记录，Codex 每次完成代码改动后覆盖。
- review.md 保存当前最新版评审意见，每次评审可覆盖。
- decision.md 只在最终收敛时写入。
- changelog.md 只追加每轮关键变更，不覆盖。

## 开发阶段

- planning：先产出 proposal.md，等待评审。
- implementation：Codex 根据已批准方案实际改代码，并写 implementation.md。
- review：Antigravity 基于 implementation.md、git diff、测试结果评审。
- fix：Codex 根据 review.md 修复问题，再回到 review。
- blocked：任一 AI 发现必须用户拍板的问题时进入此阶段。
- final：验收通过，写 decision.md 并结束。
"""


def load_workspace(session: str) -> dict:
    ensure_session(session)
    meta = load_meta(session)
    if meta.get("mode") != "development":
        return {"enabled": False, "files": [], "status": parse_workspace_status(session)}
    ensure_workspace(session, meta=meta)
    files = []
    for name, path in workspace_paths(session).items():
        modified_at = ""
        if path.exists():
            modified_at = datetime.fromtimestamp(path.stat().st_mtime).isoformat()
        files.append({
            "name": name,
            "path": str(path),
            "content": path.read_text(encoding="utf-8") if path.exists() else "",
            "modified_at": modified_at,
        })
    return {"enabled": True, "files": files, "status": parse_workspace_status(session)}


def write_workspace_file(
    session: str,
    file_name: str,
    body: str,
    append: bool = False,
) -> dict:
    ensure_session(session)
    path = workspace_file_path(session, file_name)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = body.rstrip() + "\n"
    mode = "a" if append else "w"
    with path.open(mode, encoding="utf-8") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
        fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    return {"name": normalize_workspace_file(file_name), "path": str(path)}


def append_user_decision(session: str, body: str) -> dict:
    ensure_session(session)
    text = body.strip()
    if not text:
        raise ValueError("用户决策不能为空")
    timestamp = now_iso()
    brief = workspace_file_path(session, "brief.md")
    changelog = workspace_file_path(session, "changelog.md")
    supplement = (
        f"\n## 用户补充决策 {timestamp}\n\n"
        f"{text}\n"
    )
    write_workspace_file(session, "brief.md", supplement, append=True)
    write_workspace_file(
        session,
        "changelog.md",
        f"\n## {timestamp} 用户介入\n- 用户补充决策已追加到 brief.md。\n",
        append=True,
    )
    write_workspace_file(
        session,
        "review.md",
        (
            "# Review\n\n"
            "phase: fix\n"
            "status: needs_changes\n"
            "blocking_count: 0\n"
            "sign_off: false\n"
            "needs_user_decision: false\n\n"
            "## 用户已介入\n\n"
            "用户补充决策已追加到 brief.md。请执行方重新读取 brief.md、proposal.md、"
            "implementation.md、review.md，基于用户决策继续推进。\n"
        ),
    )
    clear_blocked(session, phase="fix")
    return {"brief": str(brief), "changelog": str(changelog)}


def parse_workspace_status(session: str) -> dict:
    review_path = workspace_file_path(session, "review.md")
    decision_path = workspace_file_path(session, "decision.md")
    review_text = review_path.read_text(encoding="utf-8") if review_path.exists() else ""
    status = {
        "phase": "",
        "status": "",
        "sign_off": False,
        "blocking": False,
        "needs_user_decision": False,
        "blocking_count": 0,
        "source": "review.md",
    }
    for raw_line in review_text.splitlines()[:24]:
        if ":" not in raw_line:
            continue
        key, value = raw_line.split(":", 1)
        key = key.strip().lower().replace("-", "_")
        value = value.strip()
        if key == "status":
            status["status"] = value.lower()
        elif key == "phase":
            status["phase"] = normalize_phase(value)
        elif key == "sign_off":
            status["sign_off"] = value.lower() in {"true", "yes", "1", "approved"}
        elif key in {"blocking", "needs_user_decision"}:
            parsed = value.lower() in {"true", "yes", "1", "blocked"}
            status[key] = parsed
        elif key == "blocking_count":
            try:
                status["blocking_count"] = max(0, int(value))
            except ValueError:
                status["blocking_count"] = 0
    explicit_blocked = (
        status["status"] == "blocked"
        or status["phase"] == "blocked"
        or status["needs_user_decision"]
    )
    if explicit_blocked:
        status["blocking"] = True
        status["needs_user_decision"] = True
        status["phase"] = "blocked"
    if decision_path.exists() and decision_path.read_text(encoding="utf-8").strip() not in {
        "# Decision\n\n（最终收敛后写入结论。）",
        "# Decision\n\n(最终收敛后写入结论。)",
    }:
        status["has_decision"] = True
        if not status["phase"]:
            status["phase"] = "final"
    else:
        status["has_decision"] = False
    return status


def mark_blocked(session: str, message_id: str | None = None, reason: str = "") -> None:
    workspace_status = parse_workspace_status(session)
    state = load_state(session)
    if message_id:
        forwarded = set(state.get("forwarded_ids", []))
        forwarded.add(message_id)
        state["forwarded_ids"] = sorted(forwarded)
    state["blocked"] = True
    state["block_message_id"] = message_id
    state["block_reason"] = reason or workspace_status.get("status") or "需要用户介入"
    state["blocking_count"] = int(workspace_status.get("blocking_count") or 1)
    state["phase"] = "blocked"
    save_state(session, state)


def clear_blocked(session: str, phase: str | None = None) -> None:
    state = load_state(session)
    state["blocked"] = False
    state["block_message_id"] = None
    state["block_reason"] = None
    state["blocking_count"] = 0
    if phase:
        state["phase"] = normalize_phase(phase)
    save_state(session, state)


def append_message(
    session: str,
    from_agent: str,
    to_agent: str,
    round_no: int,
    msg_type: str,
    body: str,
    done: bool = False,
) -> dict:
    paths = ensure_session(session)
    message = {
        "id": f"msg_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}",
        "session": session,
        "from": normalize_agent(from_agent),
        "to": normalize_agent(to_agent),
        "round": int(round_no),
        "type": msg_type,
        "done": bool(done),
        "created_at": now_iso(),
        "body": body.rstrip() + "\n",
    }
    line = json.dumps(message, ensure_ascii=False)
    with paths.messages.open("a", encoding="utf-8") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        f.write(line + "\n")
        f.flush()
        os.fsync(f.fileno())
        fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    clear_awaiting_outbox_if_matches(session, message)
    return message


def load_messages(session: str) -> list[dict]:
    paths = ensure_session(session)
    messages: list[dict] = []
    for line in paths.messages.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            messages.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return messages


def load_state(session: str) -> dict:
    paths = ensure_session(session)
    state = read_json(paths.state, {"forwarded_ids": []})
    state.setdefault("forwarded_ids", [])
    state.setdefault("phase", DEFAULT_PHASE)
    if state.get("done"):
        state["phase"] = "final"
    return state


def save_state(session: str, state: dict) -> None:
    paths = ensure_session(session)
    state["updated_at"] = now_iso()
    write_json(paths.state, state)


def get_awaiting_outbox(session: str) -> dict | None:
    state = load_state(session)
    awaiting = state.get("awaiting_outbox")
    if not isinstance(awaiting, dict):
        return None
    result = dict(awaiting)
    result["elapsed_seconds"] = elapsed_seconds_since(result.get("created_at"))
    return result


def mark_awaiting_outbox(
    session: str,
    *,
    from_agent: str,
    to_agent: str | None = None,
    round_no: int | None = None,
    msg_type: str = "",
    source_message_id: str = "",
    reason: str = "",
) -> dict:
    state = load_state(session)
    state["awaiting_outbox"] = {
        "from": normalize_agent(from_agent),
        "to": normalize_agent(to_agent) if to_agent else "",
        "round": int(round_no) if round_no is not None else None,
        "type": msg_type or "",
        "source_message_id": source_message_id or "",
        "reason": reason or "",
        "created_at": now_iso(),
    }
    save_state(session, state)
    return get_awaiting_outbox(session) or {}


def clear_awaiting_outbox(session: str) -> None:
    state = load_state(session)
    if "awaiting_outbox" not in state:
        return
    state.pop("awaiting_outbox", None)
    save_state(session, state)


def _awaiting_matches_message(awaiting: dict | None, message: dict) -> bool:
    if not isinstance(awaiting, dict):
        return False
    if normalize_agent(awaiting.get("from")) != normalize_agent(message.get("from")):
        return False
    expected_round = awaiting.get("round")
    if expected_round is not None:
        try:
            if int(expected_round) != int(message.get("round")):
                return False
        except (TypeError, ValueError):
            return False
    # A valid agent response can end the session or ask the user for input, so it may
    # legitimately target `user` instead of the next peer agent.
    if message.get("done") or (message.get("type") or "") in {"final", "blocked"}:
        return True
    if normalize_agent(message.get("to")) == "user":
        return True
    expected_to = awaiting.get("to")
    if expected_to and normalize_agent(expected_to) != normalize_agent(message.get("to")):
        return False
    return True


def clear_awaiting_outbox_if_matches(session: str, message: dict) -> bool:
    awaiting = get_awaiting_outbox(session)
    if not _awaiting_matches_message(awaiting, message):
        return False
    clear_awaiting_outbox(session)
    return True


def mark_forwarded(session: str, message_id: str) -> None:
    state = load_state(session)
    forwarded = set(state.get("forwarded_ids", []))
    forwarded.add(message_id)
    state["forwarded_ids"] = sorted(forwarded)
    save_state(session, state)


def mark_done(session: str, message_id: str) -> None:
    state = load_state(session)
    forwarded = set(state.get("forwarded_ids", []))
    forwarded.add(message_id)
    state["forwarded_ids"] = sorted(forwarded)
    state["done"] = True
    state["done_message_id"] = message_id
    state["phase"] = "final"
    state.pop("awaiting_outbox", None)
    save_state(session, state)


def unmark_forwarded(session: str, message_id: str) -> None:
    state = load_state(session)
    state["forwarded_ids"] = [
        item for item in state.get("forwarded_ids", [])
        if item != message_id
    ]
    save_state(session, state)


def pending_messages(session: str) -> list[dict]:
    state = load_state(session)
    forwarded = set(state.get("forwarded_ids", []))
    return [
        msg for msg in load_messages(session)
        if msg.get("id") not in forwarded
        and (msg.get("done") or normalize_agent(msg.get("to")) in {"codex", "antigravity", "user"})
    ]


def recent_transcript(session: str, limit: int = 6) -> str:
    messages = load_messages(session)[-limit:]
    if not messages:
        return "（暂无历史消息）"
    chunks = []
    for msg in messages:
        chunks.append(
            f"[{msg.get('round')}] {msg.get('from')} -> {msg.get('to')} "
            f"({msg.get('type')}):\n{msg.get('body', '').strip()}"
        )
    return "\n\n".join(chunks)


def list_sessions() -> list[dict]:
    DEFAULT_RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    result = []
    for root in sorted(DEFAULT_RUNTIME_DIR.iterdir(), key=lambda p: p.name):
        if not root.is_dir():
            continue
        session = root.name
        paths = session_paths(session)
        if not paths.meta.exists():
            continue
        meta = read_json(paths.meta, {})
        state = load_state(session)
        messages = load_messages(session)
        last = messages[-1] if messages else None
        created_at = meta.get("created_at") or (messages[0].get("created_at") if messages else None)
        result.append({
            "session": session,
            "topic": meta.get("topic") or "",
            "mode": meta.get("mode") or DEFAULT_MODE,
            "phase": state.get("phase") or DEFAULT_PHASE,
            "created_at": created_at,
            "updated_at": state.get("updated_at") or meta.get("updated_at"),
            "done": bool(state.get("done")),
            "message_count": len(messages),
            "pending_count": len(pending_messages(session)),
            "last_message": last,
        })
    return sorted(result, key=lambda item: item.get("updated_at") or "", reverse=True)


def delete_session(session: str) -> bool:
    paths = session_paths(session)
    root = paths.root
    if not root.exists():
        return False
    if not root.is_dir() or root.parent.resolve() != DEFAULT_RUNTIME_DIR.resolve():
        raise ValueError("非法会话目录")
    shutil.rmtree(root)
    return True


def session_snapshot(session: str) -> dict:
    paths = ensure_session(session)
    messages = load_messages(session)
    state = load_state(session)
    workspace = load_workspace(session)
    workspace_status = workspace.get("status") or {}
    if workspace_status.get("phase"):
        state["phase"] = workspace_status["phase"]
    elif state.get("done"):
        state["phase"] = "final"
    awaiting = None if state.get("done") else get_awaiting_outbox(session)
    if awaiting:
        state["awaiting_outbox"] = awaiting
    else:
        state.pop("awaiting_outbox", None)
    return {
        "meta": load_meta(session),
        "state": state,
        "messages": messages,
        "workspace": workspace,
        "pending_count": len(pending_messages(session)),
        "paths": {
            "root": str(paths.root),
            "messages": str(paths.messages),
            "state": str(paths.state),
            "meta": str(paths.meta),
            "workspace": str(paths.workspace),
        },
    }


def normalize_agent(value: str | None) -> str:
    text = (value or "").strip().lower()
    aliases = {
        "ag": "antigravity",
        "anti": "antigravity",
        "antigravity": "antigravity",
        "codex": "codex",
        "user": "user",
        "human": "user",
    }
    return aliases.get(text, text)


def normalize_mode(value: str | None) -> str:
    text = (value or DEFAULT_MODE).strip().lower()
    aliases = {
        "dev": "development",
        "develop": "development",
        "development": "development",
        "开发": "development",
        "开发模式": "development",
        "chat": "chat",
        "casual": "chat",
        "闲聊": "chat",
        "闲聊模式": "chat",
        "debate": "debate",
        "辩论": "debate",
        "辩论模式": "debate",
    }
    return aliases.get(text, DEFAULT_MODE)


def normalize_phase(value: str | None) -> str:
    text = (value or "").strip().lower().replace("-", "_")
    aliases = {
        "plan": "planning",
        "planning": "planning",
        "方案": "planning",
        "计划": "planning",
        "implement": "implementation",
        "implementation": "implementation",
        "coding": "implementation",
        "实现": "implementation",
        "开发": "implementation",
        "review": "review",
        "评审": "review",
        "fix": "fix",
        "repair": "fix",
        "修复": "fix",
        "blocked": "blocked",
        "block": "blocked",
        "阻塞": "blocked",
        "final": "final",
        "done": "final",
        "结束": "final",
    }
    return aliases.get(text, text)


def normalize_workspace_file(file_name: str) -> str:
    name = Path(file_name or "").name
    if name not in WORKSPACE_FILE_NAMES:
        allowed = ", ".join(WORKSPACE_FILE_NAMES)
        raise ValueError(f"不允许的工作文档：{file_name}，只允许：{allowed}")
    return name

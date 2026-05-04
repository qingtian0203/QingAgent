from __future__ import annotations

import argparse
import sys

from .relay import relay_once, relay_watch, start_demo
from .store import (
    DEFAULT_SESSION,
    DEFAULT_TOPIC,
    WORKSPACE_FILE_NAMES,
    append_message,
    ensure_session,
    load_messages,
    session_paths,
    write_workspace_file,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="QingAgent 多 AI 协作群聊")
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser("init", help="初始化一个群聊会话")
    init.add_argument("--session", default=DEFAULT_SESSION)
    init.add_argument("--topic", default=DEFAULT_TOPIC)

    start = sub.add_parser("start", help="把初始任务发送给指定 Agent")
    start.add_argument("--session", default=DEFAULT_SESSION)
    start.add_argument("--topic", default=DEFAULT_TOPIC)
    start.add_argument("--target", default="codex", choices=["codex", "antigravity"])
    start.add_argument("--dry-run", action="store_true")

    append = sub.add_parser("append", help="向本地消息文件追加一条 Agent 回复")
    append.add_argument("--session", required=True)
    append.add_argument("--from", dest="from_agent", required=True)
    append.add_argument("--to", dest="to_agent", required=True)
    append.add_argument("--round", dest="round_no", required=True, type=int)
    append.add_argument("--type", dest="msg_type", default="reply")
    append.add_argument("--done", action="store_true")
    append.add_argument("--body", default="")

    doc = sub.add_parser("doc", help="写入开发模式工作文档")
    doc.add_argument("--session", required=True)
    doc.add_argument("--file", required=True, choices=WORKSPACE_FILE_NAMES)
    doc.add_argument("--append", action="store_true")
    doc.add_argument("--body", default="")

    relay = sub.add_parser("relay", help="转发本地消息文件里的未处理消息")
    relay.add_argument("--session", default=DEFAULT_SESSION)
    relay.add_argument("--once", action="store_true")
    relay.add_argument("--watch", action="store_true")
    relay.add_argument("--interval", type=float, default=3.0)
    relay.add_argument("--max-total", type=int, default=20)
    relay.add_argument("--max-forwards", type=int, default=1)
    relay.add_argument("--dry-run", action="store_true")

    list_cmd = sub.add_parser("list", help="查看当前会话消息")
    list_cmd.add_argument("--session", default=DEFAULT_SESSION)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.command == "init":
        paths = ensure_session(args.session, topic=args.topic)
        print(f"✅ 已初始化会话：{args.session}")
        print(f"messages: {paths.messages}")
        return 0

    if args.command == "start":
        ok = start_demo(
            session=args.session,
            topic=args.topic,
            target_agent=args.target,
            dry_run=args.dry_run,
        )
        return 0 if ok else 1

    if args.command == "append":
        body = args.body or sys.stdin.read()
        if not body.strip():
            print("❌ 缺少消息正文：请用 --body 或 stdin 传入", file=sys.stderr)
            return 2
        try:
            msg = append_message(
                session=args.session,
                from_agent=args.from_agent,
                to_agent=args.to_agent,
                round_no=args.round_no,
                msg_type=args.msg_type,
                body=body,
                done=args.done,
            )
        except Exception as exc:
            print(f"❌ outbox 写入失败：{exc}", file=sys.stderr)
            return 1
        print(f"[已写入 outbox: msg_id={msg['id']}]")
        return 0

    if args.command == "doc":
        body = args.body or sys.stdin.read()
        if not body.strip():
            print("❌ 缺少文档正文：请用 --body 或 stdin 传入", file=sys.stderr)
            return 2
        result = write_workspace_file(
            session=args.session,
            file_name=args.file,
            body=body,
            append=args.append,
        )
        action = "追加" if args.append else "写入"
        print(f"[已{action} workspace/{result['name']}: {result['path']}]")
        return 0

    if args.command == "relay":
        ensure_session(args.session)
        if args.watch:
            relay_watch(
                session=args.session,
                dry_run=args.dry_run,
                interval=args.interval,
                max_total=args.max_total,
            )
        else:
            relay_once(
                session=args.session,
                dry_run=args.dry_run,
                max_forwards=args.max_forwards,
            )
        return 0

    if args.command == "list":
        paths = session_paths(args.session)
        messages = load_messages(args.session)
        print(f"messages: {paths.messages}")
        for msg in messages:
            print(
                f"- {msg.get('id')} [{msg.get('round')}] "
                f"{msg.get('from')} -> {msg.get('to')} "
                f"{msg.get('type')} done={msg.get('done')}"
            )
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())

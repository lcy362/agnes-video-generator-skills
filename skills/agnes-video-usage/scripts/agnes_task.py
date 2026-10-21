#!/usr/bin/env python3
"""Operate the agnes-video-generator service from the command line.

Standard library only. The service base URL comes from --base or AGNES_VIDEO_BASE
(default http://localhost:8765). This script never handles credentials - the service
uses its own configured API key.

Usage:
  agnes_task.py create --type creative --field idea="..." [--field k=v ...]
  agnes_task.py status <task_id> [--wait] [--interval 10] [--timeout 3600]
  agnes_task.py list [--awaiting] [--status running,queued] [--limit 20]
  agnes_task.py mode <task_id> manual|auto
  agnes_task.py checkpoints <task_id> [checkpoint]
  agnes_task.py impact <task_id> <checkpoint>
  agnes_task.py approve <task_id> <checkpoint> [--modified id[,id...]] [--params JSON] [--confirm]
  agnes_task.py regen <task_id> <checkpoint>
  agnes_task.py stop <task_id>
  agnes_task.py resume <task_id>
  agnes_task.py download <task_id> -o out.mp4

Add --json to any command for machine-readable output.

When AGNES_HOME is set, ``status`` also writes a snapshot to
``$AGNES_HOME/tasks/<task_id>.json`` so a later session can resume without re-asking.

Exit codes: 0 success, 1 error or a failed task, 2 the task is in a non-terminal state
after --timeout.

File uploads (reference images, storyboard images) are intentionally not supported here;
use the web UI or curl -F for those.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

TERMINAL = {"completed", "failed"}
NON_TERMINAL_WAIT = 2

# Deliberately ignore HTTP proxies. On macOS urllib reads the system proxy settings but not their
# exception list, so a configured proxy turns every localhost call into a 502 from the proxy.
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

CREATE_ENDPOINTS = {
    "simple": "/api/tasks/simple",
    "creative": "/api/tasks/creative",
    "manuscript": "/api/tasks/manuscript",
    "anchor": "/api/tasks/anchor",
    "poetry": "/api/tasks/poetry",
    "image": "/api/image/generate",
}


def die(message: str, code: int = 1) -> "None":
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(code)


def base_url(args: argparse.Namespace) -> str:
    raw = getattr(args, "base", None) or os.environ.get("AGNES_VIDEO_BASE") or "http://localhost:8765"
    return raw.rstrip("/")


def _multipart(fields: dict) -> tuple:
    boundary = "----agnesvideo" + os.urandom(8).hex()
    chunks = []
    for key, value in fields.items():
        chunks.append(
            f'--{boundary}\r\nContent-Disposition: form-data; name="{key}"\r\n\r\n{value}\r\n'.encode("utf-8")
        )
    chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"


def request(args: argparse.Namespace, method: str, path: str, fields: "dict | None" = None,
            query: "dict | None" = None) -> tuple:
    """Return (status, body_bytes). Never raises for HTTP error statuses."""
    url = base_url(args) + path
    if query:
        url += "?" + urllib.parse.urlencode(query)
    data = None
    headers = {"Accept": "application/json"}
    if fields is not None:
        data, content_type = _multipart(fields)
        headers["Content-Type"] = content_type
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with _OPENER.open(req, timeout=120) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()
    except urllib.error.URLError as exc:
        die(
            f"cannot reach {url}: {exc.reason}\n"
            "Is the service running? Start it with ./start.sh, or set AGNES_VIDEO_BASE."
        )
    except OSError as exc:  # pragma: no cover - defensive
        die(f"cannot reach {url}: {exc}")


def as_json(body: bytes):
    try:
        return json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None


def detail_of(body: bytes) -> str:
    payload = as_json(body)
    if isinstance(payload, dict) and "detail" in payload:
        detail = payload["detail"]
        return detail if isinstance(detail, str) else json.dumps(detail, ensure_ascii=False)
    text = body.decode("utf-8", "replace").strip()
    return text[:400] if text else "(empty response - if this is a 502/503/504, the service is probably not running)"


def get_json(args: argparse.Namespace, path: str, query: "dict | None" = None) -> dict:
    status, body = request(args, "GET", path, query=query)
    payload = as_json(body)
    if status != 200 or payload is None:
        die(f"GET {path} -> HTTP {status}: {detail_of(body)}")
    return payload


def post_fields(args: argparse.Namespace, path: str, fields: "dict | None" = None) -> dict:
    status, body = request(args, "POST", path, fields=fields or {})
    payload = as_json(body)
    if status not in (200, 202) or payload is None:
        die(f"POST {path} -> HTTP {status}: {detail_of(body)}")
    return payload


def emit(args: argparse.Namespace, payload, render) -> None:
    if getattr(args, "json", False):
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        render(payload)


def parse_fields(pairs: "list | None") -> dict:
    out = {}
    for pair in pairs or []:
        if "=" not in pair:
            die(f"--field expects key=value, got {pair!r}")
        key, value = pair.split("=", 1)
        out[key.strip()] = value
    return out


def parse_list(raw: "str | None") -> list:
    if not raw:
        return []
    try:
        value = json.loads(raw)
    except ValueError:
        die(f"expected a JSON array, got {raw!r}")
    if not isinstance(value, list):
        die(f"expected a JSON array, got {raw!r}")
    return value


def is_awaiting(state: dict) -> bool:
    manual = state.get("manual_config") or {}
    return bool(manual.get("enabled")) and state.get("status") == "pending" and bool(manual.get("current_checkpoint"))


def status_lines(state: dict) -> list:
    progress = state.get("current_progress") or 0
    try:
        progress_pct = f"{float(progress) * 100:.1f}%"
    except (TypeError, ValueError):
        progress_pct = str(progress)
    lines = [
        f"task      {state.get('task_id')}  ({state.get('task_type')})",
        f"status    {state.get('status')}",
        f"step      {state.get('current_step') or '-'}  ({state.get('current_status') or '-'})",
        f"progress  {progress_pct}",
        f"active    {'yes' if state.get('active') else 'no'}",
    ]
    message = state.get("current_message")
    if message:
        lines.append(f"message   {message}")
    manual = state.get("manual_config") or {}
    if manual.get("enabled"):
        lines.append(
            f"manual    enabled  checkpoint={manual.get('current_checkpoint') or '-'}  "
            f"pause_points={manual.get('pause_points') or '-'}"
        )
    if is_awaiting(state):
        lines.append("awaiting  YES - waiting for a human or agent at this checkpoint")
    upstream = state.get("upstream_errors")
    if upstream:
        lines.append(f"upstream  {json.dumps(upstream, ensure_ascii=False)}")
    return lines


# ── commands ────────────────────────────────────────────────────────────────


def cmd_create(args: argparse.Namespace) -> int:
    path = CREATE_ENDPOINTS[args.type]
    payload = post_fields(args, path, parse_fields(args.field))
    emit(args, payload, lambda p: print(
        f"created  task_id={p.get('task_id')}  dir_name={p.get('dir_name')}\n"
        f"next     python3 {sys.argv[0]} status {p.get('task_id')} --wait"
    ))
    return 0


def write_snapshot(state: dict) -> None:
    """Persist the latest task state under $AGNES_HOME/tasks/<id>.json.

    A later session (or a different agent) can resume polling from the file instead of
    asking the user anything. Best effort: snapshot failures never affect the command.
    """
    task_id = str(state.get("task_id") or "")
    home = os.environ.get("AGNES_HOME", "").strip()
    if not task_id or not home:
        return
    path = os.path.join(os.path.expanduser(home), "tasks", f"{task_id}.json")
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(state, fh, ensure_ascii=False)
        os.replace(tmp, path)
    except OSError:
        pass


def cmd_status(args: argparse.Namespace) -> int:
    path = f"/api/tasks/{args.task_id}"
    if not args.wait:
        state = get_json(args, path)
        write_snapshot(state)
        emit(args, state, lambda p: print("\n".join(status_lines(p))))
        return 1 if state.get("status") == "failed" else 0

    deadline = time.time() + args.timeout
    previous = None
    state = {}
    while True:
        state = get_json(args, path)
        write_snapshot(state)
        signature = (
            state.get("status"),
            state.get("current_step"),
            state.get("current_status"),
            round(float(state.get("current_progress") or 0), 3),
            state.get("current_message"),
        )
        if signature != previous:
            stamp = time.strftime("%H:%M:%S")
            print(
                f"[{stamp}] {state.get('status')}  {state.get('current_step') or '-'}"
                f"  {float(state.get('current_progress') or 0) * 100:.0f}%"
                f"  {state.get('current_message') or ''}".rstrip()
            )
            previous = signature
        if state.get("status") in TERMINAL:
            break
        if time.time() > deadline:
            print("\n".join(status_lines(state)), file=sys.stderr)
            die(f"still {state.get('status')} after {args.timeout}s - the task is not terminal yet", NON_TERMINAL_WAIT)
        time.sleep(args.interval)

    print()
    print("\n".join(status_lines(state)))
    return 1 if state.get("status") == "failed" else 0


def cmd_list(args: argparse.Namespace) -> int:
    query = {}
    if args.status:
        query["status"] = args.status
    if args.limit:
        query["limit"] = args.limit
    payload = get_json(args, "/api/tasks", query=query)
    tasks = payload.get("tasks", [])
    if args.awaiting:
        tasks = [t for t in tasks if t.get("awaiting_user")]

    def render(_payload):
        if not tasks:
            print("no tasks")
            return
        # NOTE: the list endpoint returns a lightweight projection, not the full task state -
        # it has no current_step / current_progress / current_message. Use `status <id>` for those.
        print(f"{'task_id':<14}{'type':<12}{'status':<11}{'mode':<8}{'checkpoint':<12}description")
        for task in tasks:
            description = ""
            for key in ("idea", "prompt", "manuscript_text", "script_text", "poem_text"):
                if task.get(key):
                    description = str(task[key])
                    break
            flag = "  [awaiting]" if task.get("awaiting_user") else ""
            print(
                f"{str(task.get('task_id')):<14}{str(task.get('task_type')):<12}"
                f"{str(task.get('status')):<11}{str(task.get('current_mode') or '-'):<8}"
                f"{str(task.get('current_checkpoint') or '-'):<12}"
                f"{description[:44]}{flag}"
            )

    emit(args, payload, render)
    return 0


def cmd_mode(args: argparse.Namespace) -> int:
    payload = post_fields(args, f"/api/tasks/{args.task_id}/mode", {"mode": args.mode})
    emit(args, payload, lambda p: print(
        f"mode={p.get('mode')}  checkpoint={p.get('current_checkpoint') or '-'}  changed={p.get('changed')}"
    ))
    return 0


def cmd_checkpoints(args: argparse.Namespace) -> int:
    path = f"/api/tasks/{args.task_id}/checkpoints"
    if args.checkpoint:
        path += f"/{args.checkpoint}"
    payload = get_json(args, path)

    def render(p):
        groups = p.get("checkpoints", p)
        if not isinstance(groups, dict):
            print(json.dumps(groups, ensure_ascii=False, indent=2))
            return
        if not groups:
            print("no checkpoints reported for this task")
        for name, group in groups.items():
            artifacts = (group or {}).get("artifacts", []) if isinstance(group, dict) else []
            print(f"{name}  ({len(artifacts)} artifacts)")
            for artifact in artifacts:
                print(
                    f"  - {artifact.get('artifact_id'):<32}"
                    f"path={artifact.get('path') or artifact.get('file_relpath') or '-':<40}"
                    f"exists={artifact.get('exists')}  editable={artifact.get('editable')}"
                )
        print("\nworking dir: see /api/tasks/{id}/manifest -> working_dir")

    emit(args, payload, render)
    return 0


def cmd_impact(args: argparse.Namespace) -> int:
    payload = get_json(args, f"/api/tasks/{args.task_id}/checkpoints/{args.checkpoint}/impact")
    emit(args, payload, lambda p: print(json.dumps(p, ensure_ascii=False, indent=2)))
    return 0


def cmd_approve(args: argparse.Namespace) -> int:
    fields = {}
    if args.modified:
        fields["modified_artifact_ids"] = json.dumps(
            [item.strip() for item in args.modified.split(",") if item.strip()]
        )
    if args.params:
        fields["param_updates"] = args.params
    if args.confirm:
        fields["confirmed"] = "true"
    payload = post_fields(args, f"/api/tasks/{args.task_id}/checkpoints/{args.checkpoint}/approve", fields)
    emit(args, payload, lambda p: print(
        json.dumps(p, ensure_ascii=False, indent=2)
        + ("" if args.confirm else "\n\nImpact preview only - nothing was changed. Re-run with --confirm to apply.")
    ))
    return 0


def cmd_regen(args: argparse.Namespace) -> int:
    payload = post_fields(args, f"/api/tasks/{args.task_id}/checkpoints/{args.checkpoint}/regen")
    emit(args, payload, lambda p: print(json.dumps(p, ensure_ascii=False, indent=2)))
    return 0


def cmd_stop(args: argparse.Namespace) -> int:
    payload = post_fields(args, f"/api/tasks/{args.task_id}/stop")
    emit(args, payload, lambda p: print(f"stop requested: {json.dumps(p, ensure_ascii=False)}"))
    return 0


def cmd_resume(args: argparse.Namespace) -> int:
    payload = post_fields(args, f"/api/tasks/{args.task_id}/resume")
    emit(args, payload, lambda p: print(f"resumed: {json.dumps(p, ensure_ascii=False)}"))
    return 0


def cmd_download(args: argparse.Namespace) -> int:
    status, body = request(args, "GET", f"/api/video/{args.task_id}")
    if status != 200 or not body:
        die(f"GET /api/video/{args.task_id} -> HTTP {status}: {detail_of(body)}")
    target = args.output or f"final_{args.task_id}.mp4"
    with open(target, "wb") as handle:
        handle.write(body)
    print(f"saved  {target}  ({len(body)} bytes)")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agnes_task.py",
        description="Operate the agnes-video-generator service.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--base", help="service base URL (default $AGNES_VIDEO_BASE or http://localhost:8765)")
    parser.add_argument("--json", action="store_true", help="print raw JSON")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("create", help="create a task")
    p.add_argument("--type", required=True, choices=sorted(CREATE_ENDPOINTS))
    p.add_argument("--field", action="append", metavar="key=value",
                   help="form field, repeatable (e.g. --field idea=\"...\")")
    p.set_defaults(func=cmd_create)

    p = sub.add_parser("status", help="show task state, optionally wait")
    p.add_argument("task_id")
    p.add_argument("--wait", action="store_true", help="poll until the task is terminal")
    p.add_argument("--interval", type=int, default=10, help="seconds between polls (default 10)")
    p.add_argument("--timeout", type=int, default=3600, help="give up after this many seconds (default 3600)")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("list", help="list tasks")
    p.add_argument("--awaiting", action="store_true", help="only tasks waiting at a checkpoint")
    p.add_argument("--status", help="comma-separated status filter, e.g. running,queued")
    p.add_argument("--limit", type=int, default=20)
    p.set_defaults(func=cmd_list)

    p = sub.add_parser("mode", help="switch manual / auto mode")
    p.add_argument("task_id")
    p.add_argument("mode", choices=["manual", "auto"])
    p.set_defaults(func=cmd_mode)

    p = sub.add_parser("checkpoints", help="list checkpoints and their artifacts")
    p.add_argument("task_id")
    p.add_argument("checkpoint", nargs="?")
    p.set_defaults(func=cmd_checkpoints)

    p = sub.add_parser("impact", help="preview what approving a checkpoint would discard")
    p.add_argument("task_id")
    p.add_argument("checkpoint")
    p.set_defaults(func=cmd_impact)

    p = sub.add_parser("approve", help="confirm a checkpoint (add --confirm to apply)")
    p.add_argument("task_id")
    p.add_argument("checkpoint")
    p.add_argument("--modified", help="comma-separated artifact ids you changed")
    p.add_argument("--params", help="param_updates as a JSON object")
    p.add_argument("--confirm", action="store_true", help="actually apply; without it this is a dry run")
    p.set_defaults(func=cmd_approve)

    p = sub.add_parser("regen", help="regenerate the whole checkpoint")
    p.add_argument("task_id")
    p.add_argument("checkpoint")
    p.set_defaults(func=cmd_regen)

    p = sub.add_parser("stop", help="stop a running or queued task")
    p.add_argument("task_id")
    p.set_defaults(func=cmd_stop)

    p = sub.add_parser("resume", help="resume an interrupted or paused task")
    p.add_argument("task_id")
    p.set_defaults(func=cmd_resume)

    p = sub.add_parser("download", help="download the final video")
    p.add_argument("task_id")
    p.add_argument("-o", "--output", help="output file (default final_<task_id>.mp4)")
    p.set_defaults(func=cmd_download)

    return parser


def main(argv: "list | None" = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())

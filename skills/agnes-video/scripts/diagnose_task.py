#!/usr/bin/env python3
"""Collect everything the service knows about a task, in one pass.

Reads GET /api/tasks/{id}, GET /api/tasks/{id}/diagnostics and GET /api/tasks/{id}/manifest,
then prints the facts. It does not decide a cause - interpretation is the reader's job
(see references/upstream-errors.md and references/task-forensics.md).

Usage:
  diagnose_task.py <task_id> [--json]
  diagnose_task.py --list [--failed] [--limit 20] [--json]

Base URL: --base or AGNES_VIDEO_BASE (default http://localhost:8765).
Exit codes: 0 report produced, 1 error, 3 the task itself is in the failed state.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

FAILED = 3

# Deliberately ignore HTTP proxies. On macOS urllib reads the system proxy settings but not their
# exception list, so a configured proxy turns every localhost call into a 502 from the proxy.
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


def die(message: str, code: int = 1) -> "None":
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(code)


def base_url(args: argparse.Namespace) -> str:
    raw = args.base or os.environ.get("AGNES_VIDEO_BASE") or "http://localhost:8765"
    return raw.rstrip("/")


def get(args: argparse.Namespace, path: str, query: "dict | None" = None, tolerate_404: bool = False):
    url = base_url(args) + path
    if query:
        url += "?" + urllib.parse.urlencode(query)
    try:
        with _OPENER.open(url, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if tolerate_404 and exc.code == 404:
            return None
        body = exc.read().decode("utf-8", "replace")[:300]
        hint = " (empty body - if this is a 502/503/504 the service is probably not running)" if not body.strip() else ""
        die(f"GET {path} -> HTTP {exc.code}: {body}{hint}")
    except urllib.error.URLError as exc:
        die(
            f"cannot reach {url}: {exc.reason}\n"
            "Is the service running? Start it with ./start.sh, or set AGNES_VIDEO_BASE."
        )
    except (OSError, ValueError) as exc:
        die(f"GET {path} failed: {exc}")


def hr(title: str) -> None:
    print(f"\n{title}\n{'-' * len(title)}")


def render_status(state: dict) -> None:
    manual = state.get("manual_config") or {}
    hr("state")
    print(f"task_id        {state.get('task_id')}")
    print(f"task_type      {state.get('task_type')}")
    print(f"status         {state.get('status')}")
    print(f"current_step   {state.get('current_step') or '-'}  ({state.get('current_status') or '-'})")
    print(f"progress       {float(state.get('current_progress') or 0) * 100:.1f}%")
    print(f"active         {state.get('active')}")
    print(f"created_at     {state.get('created_at') or '-'}")
    print(f"updated_at     {state.get('updated_at') or '-'}")
    if state.get("current_message"):
        print(f"message        {state['current_message']}")
    if state.get("current_message_key"):
        print(f"message_key    {state['current_message_key']}  {state.get('current_message_params') or ''}")
    if manual:
        print(
            f"manual         enabled={manual.get('enabled')} checkpoint={manual.get('current_checkpoint') or '-'} "
            f"pause_points={manual.get('pause_points') or '-'}"
        )
    awaiting = bool(manual.get("enabled")) and state.get("status") == "pending" and manual.get("current_checkpoint")
    print(f"awaiting_user  {awaiting}")
    if state.get("upstream_errors"):
        print(f"upstream_errs  {json.dumps(state['upstream_errors'], ensure_ascii=False)}")
    if state.get("error_traceback"):
        hr("error_traceback")
        print(state["error_traceback"].rstrip())


def render_diagnostics(diag: dict) -> None:
    if not diag:
        hr("diagnostics")
        print("endpoint unavailable (older version?) - no error log data")
        return
    summary = diag.get("summary") or {}
    hr("diagnostics")
    print(f"ok             {diag.get('ok')}")
    print(f"match_source   {diag.get('match_source')}   (window matches may belong to other tasks)")
    if summary.get("error_traceback") and not summary.get("_shown"):
        print(f"traceback      {summary['error_traceback'].lstrip()[:600]}")
    logs = diag.get("error_logs") or []
    print(f"error_logs     {len(logs)} entries")
    for entry in logs:
        print(
            f"  {entry.get('timestamp')}  {entry.get('model_type')}/{entry.get('api_method')}  "
            f"HTTP {entry.get('status_code')}  {entry.get('error_type')}  "
            f"retries={entry.get('retry_count')}"
        )
        message = (entry.get("error_message") or "").replace("\n", " ")[:200]
        if message:
            print(f"      {message}")


def render_manifest(manifest: dict) -> None:
    hr("artifacts")
    if not manifest:
        print("manifest unavailable")
        return
    print(f"working_dir    {manifest.get('working_dir')}")
    print(f"dir_name       {manifest.get('dir_name')}")
    artifacts = manifest.get("artifacts") or []
    files = manifest.get("files") or []
    print(f"artifacts      {len(artifacts)} declared, {len(files)} files in the tree")
    missing = [a for a in artifacts if a.get("exists") is False]
    for artifact in artifacts:
        flag = "" if artifact.get("exists") else "  <-- MISSING"
        print(
            f"  - {str(artifact.get('artifact_id')):<32}"
            f"{str(artifact.get('path')):<40}"
            f"editable={artifact.get('editable')}{flag}"
        )
    if missing:
        print(f"\n{mapping_note(len(missing))}")
    if files:
        total = sum(int(f.get("size") or 0) for f in files)
        print(f"total file size {total / 1048576:.1f} MiB")


def mapping_note(count: int) -> str:
    return f"fact: {count} declared artifact(s) are missing on disk (deleted, cascaded, or never produced)"


def render_list(args: argparse.Namespace) -> int:
    query = {"limit": args.limit}
    payload = get(args, "/api/tasks", query=query)
    tasks = payload.get("tasks", [])
    if args.failed:
        tasks = [t for t in tasks if t.get("status") == "failed"]
    if getattr(args, "json", False):
        print(json.dumps(tasks, ensure_ascii=False, indent=2))
        return 0
    if not tasks:
        print("no matching tasks")
        return 0
    # The list endpoint returns a lightweight projection - no current_step / current_message /
    # updated_at. Diagnose one task by id for those.
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
            f"{description[:42]}{flag}"
        )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="diagnose_task.py",
        description="Collect service-side evidence for one task (or list recent tasks).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("task_id", nargs="?")
    parser.add_argument("--list", action="store_true", help="list tasks instead of diagnosing one")
    parser.add_argument("--failed", action="store_true", help="with --list: only failed tasks")
    parser.add_argument("--limit", type=int, default=20, help="with --list: page size")
    parser.add_argument("--base", help="service base URL")
    parser.add_argument("--json", action="store_true", help="raw JSON output")
    args = parser.parse_args()

    if args.list or not args.task_id:
        if not args.list and not args.task_id:
            parser.error("provide a task_id, or use --list")
        return render_list(args)

    state = get(args, f"/api/tasks/{args.task_id}")
    diagnostics = get(args, f"/api/tasks/{args.task_id}/diagnostics", tolerate_404=True)
    manifest = get(args, f"/api/tasks/{args.task_id}/manifest", tolerate_404=True)

    if args.json:
        print(json.dumps(
            {"state": state, "diagnostics": diagnostics, "manifest": manifest},
            ensure_ascii=False, indent=2,
        ))
    else:
        print(f"diagnosis for task {args.task_id} @ {base_url(args)}")
        render_status(state)
        render_diagnostics(diagnostics)
        render_manifest(manifest)
        hr("next")
        print("match the facts above against references/upstream-errors.md (status codes, queue full,")
        print("stuck inference) or references/resolution-orientation.md and subtitle-timeline.md.")

    return FAILED if state.get("status") == "failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())

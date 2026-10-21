#!/usr/bin/env python3
"""Bootstrap the agnes-video-generator service for agent use.

Standard library only. Contract: ``references/bootstrap-contract.md``.

Design notes that matter:

- This script never uses the npm package's ``bin/cli.js`` to run the service.
  npm is treated as a *distribution vehicle* only: it drops the source tree in
  ``$AGNES_HOME/runtime``. We then create the virtualenv ourselves in
  ``$AGNES_HOME/venv`` and spawn ``server.py`` directly. Two reasons:
    1. ``bin/cli.js`` creates its venv inside the package directory, which for
       npx lives in ``~/.npm/_npx/<hash>`` — an npm cache clean or a version
       bump re-downloads every Python dependency.
    2. It runs ``pip install -r requirements.txt`` on every start.
  Owning the venv keeps the install stable and lets us skip pip via a
  requirements fingerprint.
- Everything the script writes stays under ``$AGNES_HOME``. Nothing is cloned
  or installed into the user's current directory, and the skill directory itself
  is treated as read-only (it may be a symlink).
- Exit codes are the interface; agents branch on them instead of parsing text.

Usage:
  bootstrap.py probe      [--json]
  bootstrap.py install    [--json] [--route c|b|a] [--version SPEC] [--yes] [--force]
  bootstrap.py start      [--json] [--port N]
  bootstrap.py stop       [--json]
  bootstrap.py status     [--json]
  bootstrap.py verify     [--json]            # read-only readiness proof, no upstream quota
  bootstrap.py config-key [--json]            # reads the key from stdin
  bootstrap.py uninstall  [--yes]

Exit codes:
   0  ready (already running counts as ready)
  10  ready except an API key is missing
  11  API key present but rejected (usually a domain/key mismatch)
  20  needs the user's consent (install, or nothing installed yet)
  30  environment unsupported (no python3 3.10+, no node, no docker)
  40  installed but below the version this skill expects
  50  the port is taken by something that is not this service
   1  unexpected error
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

PKG_NAME = "free-short-video"
DEFAULT_PORT = 8765
CONFIG_TIMEOUT = 4.0
READY_TIMEOUT = 90.0
LOCK_STALE_SECONDS = 900

# Deliberately ignore proxies: urllib reads the macOS system proxy but not its
# exception list, so a configured proxy turns every localhost call into a 502.
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))


# ── paths ────────────────────────────────────────────────────────────────────


def home_dir() -> Path:
    raw = os.environ.get("AGNES_HOME", "").strip()
    return Path(raw).expanduser() if raw else Path.home() / ".agnes-video"


class Paths:
    def __init__(self, home: Path, port: int):
        self.home = home
        self.port = port
        self.runtime = home / "runtime"
        self.venv = home / "venv"
        self.config = home / "config"
        self.workspace = home / "workspace"
        self.outputs = home / "outputs"
        self.tasks = home / "tasks"
        self.logs = home / "logs"
        self.reports = home / "reports"
        self.tmp = home / "tmp"
        self.src = home / "src"
        self.state = home / "install.json"
        self.lock = home / "lock"
        self.pid = home / "server.pid"
        self.server_log = self.logs / "server.log"

    def ensure(self) -> None:
        for d in (
            self.home, self.config, self.workspace, self.outputs,
            self.tasks, self.logs, self.reports, self.tmp,
        ):
            d.mkdir(parents=True, exist_ok=True)

    @property
    def pkg_root(self) -> Path:
        return self.runtime / "node_modules" / PKG_NAME

    def venv_python(self) -> Path:
        if os.name == "nt":
            return self.venv / "Scripts" / "python.exe"
        return self.venv / "bin" / "python"

    def venv_pip(self) -> Path:
        if os.name == "nt":
            return self.venv / "Scripts" / "pip.exe"
        return self.venv / "bin" / "pip"


def parse_port(argv_port: str | None) -> int:
    raw = argv_port or os.environ.get("PORT") or str(DEFAULT_PORT)
    try:
        port = int(raw)
    except ValueError:
        die(f"invalid port: {raw}")
    if not 1 <= port <= 65535:
        die(f"invalid port: {raw}")
    return port


def base_url(port: int) -> str:
    override = os.environ.get("AGNES_VIDEO_BASE", "").strip()
    return override.rstrip("/") if override else f"http://127.0.0.1:{port}"


# ── http ─────────────────────────────────────────────────────────────────────


def http(method: str, path: str, base: str, payload: bytes | None = None,
         headers: dict | None = None, timeout: float = 10.0) -> tuple[int, bytes]:
    req = urllib.request.Request(f"{base}{path}", data=payload, method=method)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with _OPENER.open(req, timeout=timeout) as resp:
            return resp.status, resp.read()
    except urllib.error.HTTPError as e:
        try:
            return e.code, e.read()
        except Exception:
            return e.code, b""
    except (urllib.error.URLError, OSError):
        return 0, b""


def form(fields: dict[str, str]) -> tuple[bytes, dict[str, str]]:
    boundary = "----agnesbootstrap" + hashlib.md5(
        os.urandom(8) + str(time.time()).encode()
    ).hexdigest()
    out = []
    for name, value in fields.items():
        out.append(f"--{boundary}\r\n")
        out.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n')
        out.append(f"{value}\r\n")
    out.append(f"--{boundary}--\r\n")
    body = "".join(out).encode()
    return body, {"Content-Type": f"multipart/form-data; boundary={boundary}"}


def service_info(base: str) -> dict:
    status, raw = http("GET", "/api/config", base, timeout=CONFIG_TIMEOUT)
    if status != 200:
        return {"reachable": False}
    try:
        data = json.loads(raw.decode() or "{}")
    except json.JSONDecodeError:
        return {"reachable": True}
    masked = str(data.get("api_key") or "")
    active = data.get("active_workspace") or {}
    return {
        "reachable": True,
        "version": data.get("app_version", ""),
        "has_key": bool(masked),
        "key_source": data.get("source", ""),
        "domain": data.get("agnes_domain", ""),
        "workspace": active.get("path", "") if isinstance(active, dict) else "",
    }


def port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.6)
        return s.connect_ex(("127.0.0.1", port)) == 0


def wait_ready(base: str, timeout: float = READY_TIMEOUT) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if service_info(base).get("reachable"):
            return True
        time.sleep(1.0)
    return False


# ── install state ────────────────────────────────────────────────────────────


def read_state(paths: Paths) -> dict:
    try:
        return json.loads(paths.state.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def write_state(paths: Paths, state: dict) -> None:
    paths.state.parent.mkdir(parents=True, exist_ok=True)
    tmp = paths.state.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
    tmp.replace(paths.state)


def skill_version() -> str:
    try:
        text = (Path(__file__).resolve().parent.parent / "SKILL.md").read_text(encoding="utf-8")
    except OSError:
        return "0.0.0"
    m = re.search(r"^version:\s*([0-9][0-9A-Za-z.\-]*)", text, re.M)
    return m.group(1) if m else "0.0.0"


def requires_service() -> str:
    raw = os.environ.get("AGNES_REQUIRES_SERVICE", "").strip()
    if raw:
        return raw
    try:
        text = (Path(__file__).resolve().parent.parent / "SKILL.md").read_text(encoding="utf-8")
    except OSError:
        return ""
    m = re.search(r"^requires_service:\s*[\"']?([<>=~^0-9][^\"'\n]*)", text, re.M)
    return m.group(1).strip() if m else ""


def version_tuple(value: str) -> tuple:
    nums = re.findall(r"\d+", value or "")
    return tuple(int(n) for n in nums[:3]) if nums else (0,)


def version_satisfies(installed: str, spec: str) -> bool:
    if not spec or not installed:
        return True
    m = re.match(r"^(>=|>|<=|<|==)?\s*([0-9][0-9A-Za-z.\-]*)$", spec.strip())
    if not m:
        return True
    op, want = m.group(1) or ">=", m.group(2)
    have_t, want_t = version_tuple(installed), version_tuple(want)
    return {
        ">=": have_t >= want_t,
        ">": have_t > want_t,
        "<=": have_t <= want_t,
        "<": have_t < want_t,
        "==": have_t == want_t,
    }[op]


# ── environment probes ───────────────────────────────────────────────────────


def which(cmd: str) -> str:
    return shutil.which(cmd) or ""


def cmd_version(argv: list[str]) -> str:
    try:
        out = subprocess.run(argv, capture_output=True, text=True, timeout=20)
        return (out.stdout or out.stderr).strip().splitlines()[0]
    except (OSError, subprocess.SubprocessError, IndexError):
        return ""


def python_ok() -> bool:
    """The service needs Python 3.10+; we only need to *find* a usable one."""
    for exe in (sys.executable, which("python3"), which("python")):
        if not exe:
            continue
        v = cmd_version([exe, "-c", "import sys;print('%d.%d' % sys.version_info[:2])"])
        m = re.match(r"^(\d+)\.(\d+)$", v)
        if m and (int(m.group(1)), int(m.group(2))) >= (3, 10):
            return True
    return False


def pick_python() -> str:
    for exe in (sys.executable, which("python3"), which("python")):
        if not exe:
            continue
        v = cmd_version([exe, "-c", "import sys;print('%d.%d' % sys.version_info[:2])"])
        m = re.match(r"^(\d+)\.(\d+)$", v)
        if m and (int(m.group(1)), int(m.group(2))) >= (3, 10):
            return exe
    return ""


# ── lock ─────────────────────────────────────────────────────────────────────


class Lock:
    """Single-flight guard so two agents never install or start concurrently."""

    def __init__(self, path: Path):
        self.path = path
        self.held = False

    def acquire(self, wait: float = 240.0) -> bool:
        deadline = time.time() + wait
        while time.time() < deadline:
            try:
                fd = os.open(str(self.path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            except FileExistsError:
                if self._stale():
                    try:
                        self.path.unlink()
                    except OSError:
                        pass
                    continue
                time.sleep(2.0)
                continue
            with os.fdopen(fd, "w") as fh:
                fh.write(json.dumps({"pid": os.getpid(), "at": time.time()}))
            self.held = True
            return True
        return False

    def _stale(self) -> bool:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return True
        return (time.time() - float(data.get("at", 0))) > LOCK_STALE_SECONDS

    def release(self) -> None:
        if self.held:
            try:
                self.path.unlink()
            except OSError:
                pass
            self.held = False

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self.release()


# ── npm / venv ───────────────────────────────────────────────────────────────


def run(argv: list[str], cwd: Path | None = None, timeout: float = 1800.0) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            argv, cwd=str(cwd) if cwd else None, capture_output=True, text=True, timeout=timeout,
        )
    except (OSError, subprocess.SubprocessError) as e:
        return 1, str(e)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def npm_install(paths: Paths, spec: str) -> tuple[bool, str]:
    npm = which("npm")
    if not npm:
        return False, "npm not found"
    paths.runtime.mkdir(parents=True, exist_ok=True)
    code, out = run([
        npm, "install", "--prefix", str(paths.runtime), f"{PKG_NAME}@{spec}",
        "--no-audit", "--no-fund", "--loglevel=error",
    ])
    if code != 0 or not paths.pkg_root.exists():
        return False, out.strip()[-1500:]
    return True, out.strip()[-500:]


def requirements_sha(pkg_root: Path) -> str:
    req = pkg_root / "requirements.txt"
    try:
        return hashlib.sha256(req.read_bytes()).hexdigest()
    except OSError:
        return ""


def ensure_venv(paths: Paths, pkg_root: Path, state: dict) -> tuple[bool, str]:
    """Create the venv once; run pip only when requirements actually changed."""
    py = pick_python()
    if not py:
        return False, "python 3.10+ not found"
    if not paths.venv_python().exists():
        code, out = run([py, "-m", "venv", str(paths.venv)], timeout=600)
        if code != 0 or not paths.venv_python().exists():
            return False, f"venv creation failed: {out.strip()[-800:]}"
    sha = requirements_sha(pkg_root)
    marker = paths.venv / ".agnes-req.sha256"
    if sha and marker.exists() and marker.read_text(encoding="utf-8").strip() == sha:
        return True, "dependencies already installed (requirements unchanged)"
    req = pkg_root / "requirements.txt"
    if not req.exists():
        return False, f"requirements.txt missing under {pkg_root}"
    code, out = run([
        str(paths.venv_pip()), "install", "-q", "--upgrade-strategy", "only-if-needed",
        "-r", str(req),
    ], timeout=3600)
    if code != 0:
        return False, f"pip install failed: {out.strip()[-1500:]}"
    if sha:
        marker.write_text(sha, encoding="utf-8")
    return True, "python dependencies installed"


def ffmpeg_dir(paths: Paths) -> str:
    try:
        out = subprocess.run(
            [str(paths.venv_python()), "-c",
             "import imageio_ffmpeg;print(imageio_ffmpeg.get_ffmpeg_exe())"],
            capture_output=True, text=True, timeout=60,
        )
        exe = (out.stdout or "").strip()
        return str(Path(exe).parent) if exe else ""
    except (OSError, subprocess.SubprocessError):
        return ""


# ── service lifecycle ────────────────────────────────────────────────────────


def docker_container() -> str:
    return os.environ.get("AGNES_DOCKER_CONTAINER", "agnes-video")


def start_service(paths: Paths, base: str, state: dict) -> tuple[int, list[str]]:
    """Start (or reuse) the service. Returns (exit code, hints)."""
    hints: list[str] = []
    if service_info(base).get("reachable"):
        ensure_workspace(paths, base)
        if not service_info(base).get("has_key"):
            return 10, ["service already running — reused; the only missing piece is an API key"]
        return 0, ["service already running — reused, nothing installed or restarted"]

    if not state:
        return 20, ["nothing installed yet: run `bootstrap.py install` first"]

    route = state.get("route", "c")
    if route == "b":
        docker = which("docker")
        if not docker:
            return 30, ["installed via docker but the docker CLI is no longer on PATH"]
        run([docker, "start", docker_container()], timeout=120)
    else:
        if port_open(paths.port):
            return 50, [
                f"port {paths.port} is taken by another program",
                "pick another port with --port and retry",
            ]
        python = paths.venv_python()
        pkg_root = Path(state.get("pkg_root", ""))
        if not python.exists() or not (pkg_root / "server.py").exists():
            return 20, [
                "install record is stale (venv or source tree is gone)",
                "re-run `bootstrap.py install --force`",
            ]
        env = dict(os.environ)
        env["AGNES_CONFIG_DIR"] = str(paths.config)
        env["AGNES_LOG_FILE"] = str(paths.logs / "agnes.log")
        env["HOST"] = os.environ.get("AGNES_HOST", "127.0.0.1")
        env["PORT"] = str(paths.port)
        extra = ffmpeg_dir(paths)
        if extra:
            env["PATH"] = extra + os.pathsep + env.get("PATH", "")
        paths.logs.mkdir(parents=True, exist_ok=True)
        with open(paths.server_log, "ab") as log:
            proc = subprocess.Popen(
                [str(python), "server.py"], cwd=str(pkg_root), env=env,
                stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                start_new_session=(os.name != "nt"),
            )
        paths.pid.write_text(str(proc.pid), encoding="utf-8")

    if not wait_ready(base):
        hints.append(f"service did not answer within {int(READY_TIMEOUT)}s")
        hints.append(f"last log lines: {server_log_tail(paths)}")
        return 1, hints

    ensure_workspace(paths, base)
    if not service_info(base).get("has_key"):
        hints.append("service is ready; the only missing piece is an API key")
        return 10, hints
    return 0, hints


def server_log_tail(paths: Paths, lines: int = 25) -> str:
    try:
        text = paths.server_log.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "(no server log yet)"
    return "\n".join(text.splitlines()[-lines:])


def ensure_workspace(paths: Paths, base: str) -> None:
    """Point the service at $AGNES_HOME/workspace so artifacts stay together."""
    want = str(paths.workspace)
    info = service_info(base)
    if info.get("workspace") == want:
        return
    body, headers = form({"path": want, "name": "agnes-home"})
    status, _ = http("POST", "/api/workspaces", base, body, headers)
    if status not in (200, 409):
        # Already registered is fine; activation below is what matters.
        pass
    body, headers = form({"path": want})
    http("POST", "/api/workspaces/active", base, body, headers)


def stop_service(paths: Paths, state: dict) -> tuple[int, list[str]]:
    if state.get("route") == "b":
        docker = which("docker")
        if docker:
            run([docker, "stop", docker_container()], timeout=120)
        return 0, ["docker container stopped"]
    try:
        pid = int(paths.pid.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return 0, ["no recorded pid — nothing to stop"]
    try:
        os.kill(pid, 15)
    except OSError:
        return 0, ["process already gone"]
    for _ in range(30):
        if not port_open(paths.port):
            break
        time.sleep(0.5)
    return 0, [f"sent SIGTERM to pid {pid}"]


# ── commands ─────────────────────────────────────────────────────────────────


def cmd_probe(paths: Paths, base: str, as_json: bool) -> int:
    state = read_state(paths)
    info = service_info(base)
    key_present = info.get("has_key") if info.get("reachable") else None
    env = {
        "node": cmd_version([which("node"), "--version"]) if which("node") else "",
        "npm": which("npm"),
        "python": pick_python(),
        "docker": which("docker"),
        "git": which("git"),
    }
    needs: list[str] = []
    code = 0
    if info.get("reachable"):
        if not key_present:
            code, needs = 10, ["api_key"]
    elif not state:
        code, needs = 20, ["install"]
    elif not version_satisfies(state.get("service_version", ""), requires_service()):
        code, needs = 40, ["upgrade"]
    else:
        code, needs = 0, ["start"]

    payload = {
        "ok": code in (0,),
        "code": code,
        "home": str(paths.home),
        "base": base,
        "route": state.get("route", ""),
        "service_version": info.get("version") or state.get("service_version", ""),
        "skill_version": skill_version(),
        "requires_service": requires_service(),
        "workspace": str(paths.workspace),
        "outputs": str(paths.outputs),
        "install_present": bool(state),
        "service": info,
        "env": env,
        "needs": needs,
        "hints": [],
    }
    return emit(payload, as_json, code)


def cmd_install(paths: Paths, base: str, as_json: bool, route: str, spec: str,
                force: bool) -> int:
    paths.ensure()
    state = read_state(paths)
    if state and not force:
        installed = state.get("service_version", "")
        if not version_satisfies(installed, requires_service()):
            return emit({
                "ok": False, "code": 40, "home": str(paths.home), "base": base,
                "route": state.get("route", ""), "service_version": installed,
                "skill_version": skill_version(),
                "requires_service": requires_service(),
                "workspace": str(paths.workspace), "outputs": str(paths.outputs),
                "needs": ["upgrade"],
                "hints": [f"installed {installed} is below required {requires_service()}",
                          "re-run with --force to upgrade"],
            }, as_json, 40)
        code, hints = start_service(paths, base, state)
        return emit({
            "ok": code == 0, "code": code, "home": str(paths.home), "base": base,
            "route": state.get("route", ""), "service_version": installed,
            "skill_version": skill_version(),
            "requires_service": requires_service(),
            "workspace": str(paths.workspace), "outputs": str(paths.outputs),
            "needs": [] if code == 0 else ["api_key"],
            "hints": ["already installed — reused, no download performed"] + hints,
        }, as_json, code)

    lock = Lock(paths.lock)
    if not lock.acquire():
        return emit({
            "ok": False, "code": 1, "home": str(paths.home), "base": base,
            "route": "", "service_version": "", "skill_version": skill_version(),
            "workspace": str(paths.workspace), "outputs": str(paths.outputs),
            "needs": [], "hints": ["another install is in progress (lock not released)"],
        }, as_json, 1)
    try:
        chosen = route
        if not chosen:
            if which("node") and python_ok():
                chosen = "c"
            elif which("docker"):
                chosen = "b"
            elif which("git") and python_ok():
                chosen = "a"
            else:
                return emit({
                    "ok": False, "code": 30, "home": str(paths.home), "base": base,
                    "route": "", "service_version": "", "skill_version": skill_version(),
                    "workspace": str(paths.workspace), "outputs": str(paths.outputs),
                    "needs": ["python3.10+", "node"],
                    "hints": ["install Python 3.10+ (or Docker) and re-run"],
                }, as_json, 30)

        if chosen == "b":
            docker = which("docker")
            if not docker:
                return emit({
                    "ok": False, "code": 30, "home": str(paths.home), "base": base,
                    "route": "b", "service_version": "", "skill_version": skill_version(),
                    "workspace": str(paths.workspace), "outputs": str(paths.outputs),
                    "needs": ["docker"], "hints": ["docker CLI not found"],
                }, as_json, 30)
            image = os.environ.get("AGNES_IMAGE", "lcy362/free-short-video:latest")
            run([docker, "rm", "-f", docker_container()], timeout=120)
            code, out = run([
                docker, "run", "-d", "--name", docker_container(),
                "-p", f"{paths.port}:8765",
                "-v", f"{paths.config}:/app/.agnes_config",
                "-v", f"{paths.workspace}:/app/.working_dir",
                image,
            ], timeout=1800)
            if code != 0:
                return emit({
                    "ok": False, "code": 1, "home": str(paths.home), "base": base,
                    "route": "b", "service_version": "", "skill_version": skill_version(),
                    "workspace": str(paths.workspace), "outputs": str(paths.outputs),
                    "needs": [], "hints": [f"docker run failed: {out.strip()[-1200:]}"],
                }, as_json, 1)
            state = {"route": "b", "service_version": "docker", "pkg_root": "",
                     "created_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
        else:
            if chosen == "c":
                ok, detail = npm_install(paths, spec)
                if not ok:
                    return emit({
                        "ok": False, "code": 1, "home": str(paths.home), "base": base,
                        "route": "c", "service_version": "", "skill_version": skill_version(),
                        "workspace": str(paths.workspace), "outputs": str(paths.outputs),
                        "needs": [], "hints": [f"npm install failed: {detail}"],
                    }, as_json, 1)
                pkg_root = paths.pkg_root
            else:
                git = which("git")
                if not git:
                    return emit({
                        "ok": False, "code": 30, "home": str(paths.home), "base": base,
                        "route": "a", "service_version": "", "skill_version": skill_version(),
                        "workspace": str(paths.workspace), "outputs": str(paths.outputs),
                        "needs": ["git"], "hints": ["git CLI not found"],
                    }, as_json, 30)
                pkg_root = paths.src / "agnes-video-generator"
                if not pkg_root.exists():
                    code, out = run([
                        git, "clone", "--depth", "1",
                        "https://github.com/lcy362/agnes-video-generator.git", str(pkg_root),
                    ], timeout=1800)
                    if code != 0:
                        return emit({
                            "ok": False, "code": 1, "home": str(paths.home), "base": base,
                            "route": "a", "service_version": "",
                            "skill_version": skill_version(),
                            "workspace": str(paths.workspace), "outputs": str(paths.outputs),
                            "needs": [], "hints": [f"git clone failed: {out.strip()[-1200:]}"],
                        }, as_json, 1)

            ok, detail = ensure_venv(paths, pkg_root, state)
            if not ok:
                return emit({
                    "ok": False, "code": 1, "home": str(paths.home), "base": base,
                    "route": chosen, "service_version": "", "skill_version": skill_version(),
                    "workspace": str(paths.workspace), "outputs": str(paths.outputs),
                    "needs": [], "hints": [detail],
                }, as_json, 1)
            version = read_package_version(pkg_root)
            state = {
                "route": chosen,
                "service_version": version,
                "pkg_root": str(pkg_root),
                "venv": str(paths.venv),
                "requirements_sha256": requirements_sha(pkg_root),
                "python": str(paths.venv_python()),
                "node": cmd_version([which("node"), "--version"]) if which("node") else "",
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "skill_version": skill_version(),
            }

        write_state(paths, state)
        code, hints = start_service(paths, base, state)
        return emit({
            "ok": code == 0, "code": code, "home": str(paths.home), "base": base,
            "route": state.get("route", ""), "service_version": state.get("service_version", ""),
            "skill_version": skill_version(), "requires_service": requires_service(),
            "workspace": str(paths.workspace), "outputs": str(paths.outputs),
            "needs": [] if code == 0 else (["api_key"] if code == 10 else []),
            "hints": hints,
        }, as_json, code)
    finally:
        lock.release()


def read_package_version(pkg_root: Path) -> str:
    try:
        return json.loads((pkg_root / "package.json").read_text(encoding="utf-8")).get("version", "")
    except (OSError, json.JSONDecodeError):
        return ""


def cmd_start(paths: Paths, base: str, as_json: bool) -> int:
    paths.ensure()
    state = read_state(paths)
    code, hints = start_service(paths, base, state)
    return emit({
        "ok": code == 0, "code": code, "home": str(paths.home), "base": base,
        "route": state.get("route", ""), "service_version": state.get("service_version", ""),
        "skill_version": skill_version(), "requires_service": requires_service(),
        "workspace": str(paths.workspace), "outputs": str(paths.outputs),
        "needs": [] if code == 0 else (["api_key"] if code == 10 else []),
        "hints": hints,
    }, as_json, code)


def cmd_stop(paths: Paths, as_json: bool) -> int:
    code, hints = stop_service(paths, read_state(paths))
    return emit({"ok": code == 0, "code": code, "home": str(paths.home),
                 "hints": hints}, as_json, code)


def cmd_status(paths: Paths, base: str, as_json: bool) -> int:
    state = read_state(paths)
    info = service_info(base)
    needs = []
    if not info.get("reachable"):
        code = 0 if state else 20
        needs = [] if state else ["install"]
    elif not info.get("has_key"):
        code, needs = 10, ["api_key"]
    else:
        code = 0
    hints = []
    if state and not version_satisfies(state.get("service_version", ""), requires_service()):
        code, hints = 40, [f"installed {state.get('service_version')} < required {requires_service()}"]
    payload = {
        "ok": code == 0, "code": code, "home": str(paths.home), "base": base,
        "route": state.get("route", ""),
        "service_version": info.get("version") or state.get("service_version", ""),
        "skill_version": skill_version(), "requires_service": requires_service(),
        "workspace": str(paths.workspace), "outputs": str(paths.outputs),
        "service": info, "needs": needs, "hints": hints,
    }
    return emit(payload, as_json, code)


def cmd_verify(paths: Paths, base: str, as_json: bool) -> int:
    """Read-only readiness proof: the service answers, without touching upstream quota."""
    checks: list[dict] = []

    def check(name: str, path: str, timeout: float = 10.0) -> bool:
        status, _ = http("GET", path, base, timeout=timeout)
        checks.append({"name": name, "path": path, "status": status, "ok": status == 200})
        return status == 200

    if not service_info(base).get("reachable"):
        return emit({
            "ok": False, "code": 1, "home": str(paths.home), "base": base,
            "checks": checks,
            "hints": ["service is not answering — run `bootstrap.py start` first"],
        }, as_json, 1)

    check("config", "/api/config")
    check("voices", "/api/voices", timeout=30)
    check("tasks", "/api/tasks")
    check("index", "/")
    info = service_info(base)
    failed = [c["name"] for c in checks if not c["ok"]]
    needs = []
    if not info.get("has_key"):
        needs.append("api_key")
    code = 1 if failed else (10 if needs else 0)
    hints = [f"failed: {', '.join(failed)}"] if failed else []
    if needs:
        hints.append("service and voices are fine; the only missing piece is an API key")
    return emit({
        "ok": code == 0, "code": code, "home": str(paths.home), "base": base,
        "service_version": info.get("version", ""), "skill_version": skill_version(),
        "workspace": str(paths.workspace), "outputs": str(paths.outputs),
        "checks": checks, "needs": needs, "hints": hints,
    }, as_json, code)


def cmd_config_key(paths: Paths, base: str, as_json: bool) -> int:
    key = sys.stdin.readline().strip()
    if not key:
        return emit({"ok": False, "code": 1, "hints": [
            "no key on stdin — pipe it in: `... config-key < key.txt` (never pass it as an argument)",
        ]}, as_json, 1)
    body, headers = form({"api_key": key})
    status, _ = http("POST", "/api/config", base, body, headers)
    if status != 200:
        return emit({"ok": False, "code": 1,
                     "hints": [f"service rejected the key (HTTP {status})"]}, as_json, 1)
    # Bind each key to the domain it was issued on, then verify cheaply.
    http("POST", "/api/config/keys/detect", base, *form({}), timeout=90)
    status, raw = http("GET", "/api/models", base, timeout=90)
    if status == 200:
        write_state(paths, {**read_state(paths),
                            "key": {"source": "config", "checked_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                                    "domain": service_info(base).get("domain", "")}})
        return emit({"ok": True, "code": 0, "home": str(paths.home), "base": base,
                     "service": service_info(base), "hints": ["key accepted; domain bound"]},
                    as_json, 0)
    detail = raw.decode(errors="replace")[:400]
    return emit({
        "ok": False, "code": 11, "home": str(paths.home), "base": base,
        "hints": [
            "the service was configured but the key was rejected (HTTP %s)" % status,
            "this is almost always a domain mismatch: try com / cn / cn_bak",
            detail,
        ],
    }, as_json, 11)


def cmd_uninstall(paths: Paths, as_json: bool, confirmed: bool) -> int:
    if not confirmed:
        return emit({"ok": False, "code": 20, "home": str(paths.home),
                     "hints": [f"this deletes {paths.home}; re-run with --yes"]}, as_json, 20)
    stop_service(paths, read_state(paths))
    shutil.rmtree(paths.home, ignore_errors=True)
    return emit({"ok": True, "code": 0, "home": str(paths.home),
                 "hints": ["removed; nothing else on the machine was touched"]}, as_json, 0)


# ── output ───────────────────────────────────────────────────────────────────


def emit(payload: dict, as_json: bool, code: int) -> int:
    payload.setdefault("ok", code == 0)
    payload["code"] = code
    if as_json:
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return code
    print(f"code: {code}  ok: {payload.get('ok')}")
    for key in ("home", "base", "route", "service_version", "skill_version", "workspace", "outputs"):
        if payload.get(key):
            print(f"{key}: {payload[key]}")
    if payload.get("needs"):
        print("needs: " + ", ".join(payload["needs"]))
    for hint in payload.get("hints", []):
        print(f"hint: {hint}")
    return code


def die(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(30)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="bootstrap.py",
        description="Install, start and inspect the agnes-video-generator service.",
    )
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("--port", help=f"service port (default {DEFAULT_PORT})")
    # Global switches must also work after the subcommand (`probe --json`);
    # SUPPRESS keeps the absent case from clobbering the top-level value.
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--json", action="store_true", default=argparse.SUPPRESS)
    common.add_argument("--port", default=argparse.SUPPRESS)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("probe", parents=[common],
                   help="read-only: what exists, what is running, what is missing")
    p_install = sub.add_parser("install", parents=[common], help="install once, then start")
    p_install.add_argument("--route", choices=["c", "b", "a"], default="",
                           help="c=npm (default), b=docker, a=git clone")
    p_install.add_argument("--version", default=os.environ.get("AGNES_VIDEO_VERSION", "latest"),
                           help="npm version/range to install (default: latest)")
    p_install.add_argument("--yes", action="store_true", help="skip the consent check")
    p_install.add_argument("--force", action="store_true", help="reinstall / upgrade in place")
    sub.add_parser("start", parents=[common], help="start if needed (idempotent)")
    sub.add_parser("stop", parents=[common], help="stop the service")
    sub.add_parser("status", parents=[common], help="one-line health plus exit code")
    sub.add_parser("verify", parents=[common],
                   help="read-only readiness proof (config, voices, tasks, index)")
    sub.add_parser("config-key", parents=[common],
                   help="read an API key from stdin, bind the domain, verify")
    p_uninstall = sub.add_parser("uninstall", parents=[common], help="delete $AGNES_HOME")
    p_uninstall.add_argument("--yes", action="store_true")

    args = parser.parse_args(argv)
    port = parse_port(args.port)
    paths = Paths(home_dir(), port)
    base = base_url(port)

    if args.command == "probe":
        return cmd_probe(paths, base, args.json)
    if args.command == "install":
        if not args.yes:
            return emit({
                "ok": False, "code": 20, "home": str(paths.home), "base": base,
                "route": args.route or "c",
                "hints": [
                    "installing downloads the service and its Python dependencies",
                    "expected: 2-5 minutes, several hundred MB, written under " + str(paths.home),
                    "ask the user for consent, then re-run with --yes",
                ],
            }, args.json, 20)
        return cmd_install(paths, base, args.json, args.route, args.version, args.force)
    if args.command == "start":
        return cmd_start(paths, base, args.json)
    if args.command == "stop":
        return cmd_stop(paths, args.json)
    if args.command == "status":
        return cmd_status(paths, base, args.json)
    if args.command == "verify":
        return cmd_verify(paths, base, args.json)
    if args.command == "config-key":
        return cmd_config_key(paths, base, args.json)
    if args.command == "uninstall":
        return cmd_uninstall(paths, args.json, args.yes)
    parser.error("unknown command")
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

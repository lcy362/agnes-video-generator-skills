# Bootstrap contract

> Source anchor: upstream `bin/cli.js`, `core/config.py` (`AGNES_CONFIG_DIR`, `AGNES_WORKING_DIR`),
> `server.py` (HOST/PORT), `web/routes/workspace_routes.py`, `GET /api/config` (`has_key`).
> Verified 2026-10-21 against upstream v7.2.1.
> This file is the authority for `scripts/bootstrap.py`. When the two disagree, fix the script.

## 1. Why this script exists

The npm package is used as a **distribution vehicle only**: `bootstrap.py` installs it with
`npm --prefix` into `$AGNES_HOME/runtime`, builds its own venv in `$AGNES_HOME/venv`, skips pip when
the `requirements.txt` fingerprint is unchanged, and spawns `server.py` directly with
`AGNES_CONFIG_DIR` / `AGNES_WORKING_DIR` / `AGNES_LOG_FILE` pointing inside `$AGNES_HOME`.

Upstream history matters here, because it explains why the script does not simply delegate to
`bin/cli.js`:

| Behavior | Before v7.2.1 | Now (≥ v7.2.1) |
|----------|---------------|----------------|
| Where the venv lives | inside the package directory — under npx that is `~/.npm/_npx/<hash>`, so a cache clean or version bump re-downloaded every Python dependency | `$AGNES_HOME/venv` |
| When pip runs | every start (the log said "first run only", the call sat outside the `if venv missing` branch) | only when `requirements.txt` changed (sha256 fingerprint) |
| Startup result for scripts | interactive only | `--detach` / `--json` / `--print-paths` |

The script keeps its own venv and spawn anyway, for three reasons: the skill supports services installed
by Docker or a clone with the same code path; it must keep working if the package layout changes again;
and `bootstrap.py` needs a deterministic `install.json` to answer "is this machine ready" without
starting anything.

## 2. Directory layout

`AGNES_HOME` defaults to `~/.agnes-video`; nothing is written outside it.

```
$AGNES_HOME/
├─ install.json      record: route, service version, package root, requirements sha256, created_at
├─ lock              single-flight lock (pid + timestamp, stale after 15 min)
├─ runtime/          npm --prefix install target (route c)
├─ src/              git clone target (route a)
├─ venv/             Python dependencies + .agnes-req.sha256 fingerprint
├─ config/           AGNES_CONFIG_DIR (config.json, 0600 — contains the key)
├─ workspace/        service workspace: storyboards, clips, manifests
├─ outputs/<task>/   deliverables copied out of the workspace
├─ tasks/<id>.json   polling snapshots (lets the next session resume)
├─ reports/          redacted issue reports
├─ logs/             server.log, agnes.log
└─ tmp/
```

Hard rules: never install or clone into the user's current directory; never write into the skill
directory (it may be a read-only symlink); `uninstall --yes` is the only thing that deletes anything.

## 3. State machine

```
probe ─┬─ service.reachable ────────────────────────────────► ready (reuse, zero work)
       ├─ install.json present, version ok ──► start ───────► ready / 10
       ├─ install.json present, version low ─► 40 (upgrade with --force)
       └─ no install.json ───────────────────► 20 (consent) ─► install ─► start
```

- **Reuse beats install.** A reachable service means the answer is `0`/`10` and nothing else runs.
- **Install is idempotent.** With a valid `install.json`, `install` only starts; it never re-downloads.
- **Version gate.** `requires_service` in `SKILL.md` frontmatter is compared against
  `install.json.service_version`; below it the script returns `40` instead of running against an API
  whose shape may have moved.
- **Fingerprint gate.** `venv/.agnes-req.sha256` compared with `runtime/.../requirements.txt` — equal
  means pip is skipped, including on a cold start.
- **Single flight.** `$AGNES_HOME/lock` is created with `O_CREAT|O_EXCL`; a second agent waits (and
  then re-probes) instead of installing in parallel. A lock older than 15 minutes is treated as dead.

## 4. Exit codes

| Code | Meaning | Agent action |
|------|---------|--------------|
| 0 | Ready (including "already running") | create the task |
| 10 | Ready except no API key | run the key onboarding |
| 11 | Key present, verification failed | switch domain `com`/`cn_bak`, retry once, then treat as invalid |
| 20 | Consent needed (install) or nothing installed | explain cost, then `install --yes` |
| 30 | Environment unsupported | report what is missing, stop |
| 40 | Installed below `requires_service` | ask, then `install --force` |
| 50 | Port held by another program | ask for `--port`, never switch silently |
| 1 | Unexpected error | show the hints (they carry the tail of the real error) |

`--json` always prints one object; stable keys:
`ok, code, home, base, route, service_version, skill_version, requires_service, workspace, outputs, needs, hints`.

## 5. Routes

| Route | Trigger | What it does | Notes |
|-------|---------|--------------|-------|
| c (default) | node ≥18 and python ≥3.10 | `npm install --prefix $AGNES_HOME/runtime free-short-video@<spec>`, own venv | cross-platform, no system ffmpeg (imageio-ffmpeg is bundled and prepended to PATH) |
| b | docker available, no usable python | `docker run -d` with `config/` and `workspace/` bind-mounted | named container `agnes-video` (override `AGNES_DOCKER_CONTAINER`) |
| a | user wants to change the code | `git clone --depth 1` into `$AGNES_HOME/src`, venv from that checkout | contrib scenario only; never into the current directory |

## 6. Service start

- Spawn `venv/bin/python server.py` with `cwd=$AGNES_HOME/runtime/node_modules/free-short-video`
  (or the clone root for route a), detached from the agent's process group.
- Environment: `AGNES_CONFIG_DIR=$AGNES_HOME/config`, `AGNES_LOG_FILE=$AGNES_HOME/logs/agnes.log`,
  `HOST=127.0.0.1` (override `AGNES_HOST`), `PORT=<port>`, plus the bundled ffmpeg directory on `PATH`.
- Readiness = `GET /api/config` answering 200 within 90 s. On timeout the hints carry the last 25
  lines of `logs/server.log` — report them, do not retry blindly.
- The child process also gets `AGNES_WORKING_DIR=$AGNES_HOME/workspace`, so a fresh config already
  defaults to the right path. The workspace API calls below remain the fallback for a service that was
  already running (started by the user, or an older build that predates the variable).
- After readiness, point the service at `$AGNES_HOME/workspace` via `POST /api/workspaces` +
  `POST /api/workspaces/active`, but only when the active workspace differs.
- Readiness proof (`bootstrap.py verify`) is four read-only checks: `/api/config`, `/api/voices`,
  `/api/tasks`, `/` — all reachable without a key and without consuming upstream quota. It returns
  `0` when everything passes and a key is configured, `10` when everything passes but the key is
  missing, `1` when a check failed (the failing names are in `checks[]`).

## 7. Key handling

- The script accepts a key **only** on stdin (`config-key`), never as an argument, and never prints it.
- Preferred path remains the user pasting the key into the local web UI: the key then never touches
  the agent's context or the shell history.
- `POST /api/config` stores it under `config/config.json` (0600). `POST /api/config/keys/detect`
  binds each key to its issuing domain; `GET /api/models` is the cheap proof that it works.
- `install.json.key` stores `{source, domain, checked_at}` — never the key itself.

## 8. Uninstall

`bootstrap.py uninstall --yes` stops the service (SIGTERM, or `docker stop`) and removes
`$AGNES_HOME` only. System-level packages, the npm cache and the user's videos elsewhere are untouched.

## 9. Deliberately out of scope

- No background auto-upgrade (only `--force` or the `40` gate).
- No model or asset downloads beyond the service's own Python dependencies.
- No telemetry, no credential upload, no writing outside `$AGNES_HOME`.

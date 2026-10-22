---
name: agnes-video
description: Turn an idea into a finished video without cloning the project first - this one skill installs the agnes-video-generator service on demand into ~/.agnes-video, starts it on localhost:8765, walks the user through a free API key, picks the right pipeline (simple / creative / manuscript / anchor / poetry / image), reports progress step by step, delivers the file, diagnoses failures (503 queue-full, 401 domain mismatch, timeouts, wrong resolution, sideways portrait, broken subtitle timeline), and - once the user agrees - fixes a genuine service defect and opens a PR. Use when the user says "install / set up agnes video", "generate a video with agnes", "make a creative / manuscript / poetry / digital-human video", "run manual mode", "improve the storyboard / narration / subtitles", "check on my video task", "the task keeps failing", "the video is sideways", "subtitles are out of sync", "fix this / open a PR for agnes-video-generator".
agent_created: true
version: 1.0.0
requires_service: ">=7.2.1"
---

# agnes-video

One skill, one loop: **install → create → watch → deliver → diagnose → fix**. Every step below runs
against `$AGNES_VIDEO_BASE` (default `http://127.0.0.1:8765`).

**Do not clone the project and do not read its repository to get started.** The bootstrap script owns
installation; you own the conversation. A clone happens only in §7, when the user has agreed to change
the service's code.

## 0. The loop

```
probe ─┬─ ready ─────────────────────────────► §2 key → §3 pipeline → §4 task → §5 deliver
       ├─ installed, below version ─► upgrade ─┘
       └─ nothing ─► consent ─► install ──────┘

any failure ─► §6 diagnose (evidence, not symptom)
                  ├─ configuration / capacity ─► fix or report, stop
                  ├─ small service defect ─► confirm with user ─► §7 fix → PR
                  └─ large or unclear ─► report with evidence, stop
```

## 1. Bootstrap

```bash
python3 scripts/bootstrap.py probe  --json            # read-only: what exists, what is missing
python3 scripts/bootstrap.py install --yes --json     # once; also starts the service
python3 scripts/bootstrap.py start  --json            # idempotent; reuse if already running
python3 scripts/bootstrap.py verify --json            # readiness proof, costs no upstream quota
```

`verify` checks `/api/config`, `/api/voices`, `/api/tasks` and the index page. That is the evidence you
show the user that the machine is ready before a key exists — do not replace it with "the process
started".

Branch on the exit code, never on the text:

| Code | Meaning | What you do |
|------|---------|-------------|
| 0 | Ready | §3 |
| 10 | Ready except no API key | §2 |
| 11 | Key rejected (usually domain mismatch) | §2, switch `com` / `cn_bak`, retry once |
| 20 | Needs consent (or nothing installed) | Explain cost, then `install --yes` |
| 30 | Environment unsupported | Report the missing runtime, stop |
| 40 | Installed below `requires_service` | Ask, then `install --force` |
| 50 | Port taken by something else | Ask for another `--port`; never pick one silently |

Rules:

- Run `probe` first. If `service.reachable` is true, reuse it — do not reinstall or restart, the user
  may be watching the web UI.
- `install` costs ~2–5 minutes and several hundred MB under `$AGNES_HOME` (default `~/.agnes-video`).
  Get consent first. Nothing is written into the current working directory.
- A second run must be a no-op: same environment, no npm, no pip. If you see install output on a
  repeat run, stop and report it instead of pretending it is normal.
- Layout, state machine, lock, version gate: `references/bootstrap-contract.md`.

## 2. Key

Show the service is alive first (`GET /api/config`, `GET /api/voices`, the web UI), then say the only
missing piece is a key. Site and key must match, or every call returns `401`:

| Domain | API host | Where to get a key |
|--------|----------|--------------------|
| `com` (default) | `apihub.agnes-ai.com` | <https://platform.agnes-ai.com> |
| `cn` | `api.agnes-ai.cn` | the China site (needs a China-site key) |
| `cn_bak` | `apihub.agnes-ai.cn` | fallback; accepts global-site keys |

Hand the key over in the safest way available, in this order:

1. **Ask the user to paste it into `http://127.0.0.1:8765` themselves.** The key never enters your
   context or the shell history. Recommended.
2. `python3 scripts/bootstrap.py config-key --json` with the key on stdin (no echo, no argv).
3. `AGNES_API_KEY` — unattended/CI only. Environment keys cannot be bound per key and are skipped by
   auto-detection, so a `401` there means switching the global domain.

Then bind and prove it in one step:

```bash
POST /api/config/keys/detect     # bind each key to the domain it was issued on
GET  /api/models                 # cheap proof the key works (no generation)
```

Never echo the key, never write it to a file, never put it in a task payload.

## 3. Pick the pipeline

Full decision table (params, cost, wrong-choice symptoms, upload limits):
`references/pipeline-selection.md`. Short form:

| The user wants | Type | First field |
|----------------|------|-------------|
| One shot, 5–10 s | `simple` (t2v/i2v/ti2vid/keyframes) | `prompt` |
| A story with storyboards | `creative` | `idea` |
| Their own text → visuals | `manuscript` | `manuscript_text` |
| A talking presenter | `anchor` | character image + script |
| A poem with recitation | `poetry` | the poem |
| Just one still image | image | `prompt` |

Say the choice and the expected duration **before** submitting, and offer the cheaper alternative
("only one shot? `simple` takes minutes instead of 20"). Image uploads (first/last frame, character
image, custom storyboards) are not supported by `agnes_task.py` — use `curl -F` or ask the user to
upload in the UI.

## 4. Submit and report progress

```bash
python3 scripts/agnes_task.py create --type creative \
  --field idea="A lighthouse keeper befriends a storm petrel" \
  --field video_width=768 --field video_height=1080 --json
python3 scripts/agnes_task.py status <task_id> --wait --interval 10 --timeout 900 --json
python3 scripts/agnes_task.py download <task_id> -o <outputs>/final.mp4
```

- Check `GET /api/concurrency` first; queuing is normal and must be said out loud.
- Report **deltas only**: step change, ≥10% jump, new message, terminal state. Never dump the whole
  task state. One message per turn at most, three lines: step x/y, elapsed, what is next.
- Keep a single wait under ~90 s, then continue next turn — long videos take 10–40 minutes and must
  not block one tool call. Snapshot path and reporting template: `references/progress.md`.
- Same step with no progress for 10 minutes → check `/api/concurrency` and `upstream_errors`, explain
  why, instead of waiting silently or killing the task.
- There is **no WebSocket**; polling the same endpoint as the UI is not "taking over" the session.

## 5. Deliver

- Artifacts live under `$AGNES_HOME/workspace`; deliverables go to `$AGNES_HOME/outputs/<task_id>/`.
- If `AGNES_OUTPUT_DIR` is set, also copy the final file there (never overwrite — add `-1`).
- Always report the absolute path, plus `ffprobe` duration and resolution, and say which copy is which.

## 6. When it fails

### 6.1 Order of operations

```
1. Service or upstream?
   curl -s "$AGNES_VIDEO_BASE/api/health"
   curl -s "$AGNES_VIDEO_BASE/api/concurrency"
   → down / overloaded → fix locally, stop here

2. The task's own story (no guessing)
   python3 scripts/diagnose_task.py <task_id>
   → state, step, message, error_traceback, upstream logs, manifest, artifact health

3. Classify from the evidence
   references/upstream-errors.md         ← 503 / 429 / 401 / timeout / stuck_inference
   references/resolution-orientation.md  ← wrong size, landscape vs portrait, sideways output
   references/subtitle-timeline.md       ← subtitles wrong after resume, cue timeline

4. Only if the service reports success but the artifact is wrong: re-probe upstream
   references/upstream-probe.md          ← raw curl + ffprobe recipes
```

```bash
python3 scripts/diagnose_task.py <task_id>          # summary + errors + artifacts
python3 scripts/diagnose_task.py <task_id> --json   # machine-readable
python3 scripts/diagnose_task.py --list --failed    # recent failures, newest first
```

### 6.2 Triage

| Symptom | Most likely class | Evidence to collect |
|---------|-------------------|---------------------|
| `503` + `video_queue_full` | Upstream free-tier queue saturation (per-model pool) | body `code`; whether the same key submitted fine on another model |
| Bare `503`, no `code` | Upstream overload / no available channel | body `message`; app version (pre-7.1.0 gave up too early) |
| `429` | Rate limit | Key ring size; whether another key was tried |
| `401` invalid token | Key bound to the wrong site domain | Which domain the key is configured for: `com` / `cn` / `cn_bak` |
| Stuck then `failed` after ~15 min, "not finished after 15 minutes" | Upstream inference hard gate — waiting longer will not help | `internal_status`, `created_at`→`completed_at` delta |
| Task failed but the poll looked like HTTP 200 | Upstream reports failures **in the body** with HTTP 200 | body `status` + `error`, never the HTTP code alone |
| 404 while polling a just-submitted task | Not yet visible upstream (can take 10 min+ at peak) | Treat as intermediate, not a failure |
| Output size ≠ requested size | Upstream snapping / ratio protocol | `ffprobe` on the produced file — never `perf_params` |
| Portrait output is sideways | Known upstream 9:16 defect in the 2.5 series | `ffprobe` streams; no `Display Matrix` present |
| Subtitles misaligned after a resume | `sub_maker` recovery path | Whether the run resumed; whether cues were re-harvested |

Two rules that prevent most wrong conclusions:

1. **HTTP status is not the verdict.** Upstream returns HTTP 200 on task failure, and its `error`
   field is an object `{code, message}`. `progress` / `internal_progress` are contradictory in failure
   samples and must not be trusted.
2. **The produced file is the only truth for resolution and orientation.** `perf_params` is the
   internal inference size, not the container size, and a width/height-ratio check will happily pass a
   video whose pixels are rotated 90°.

```bash
python3 scripts/check_media.py out.mp4     # container size, rotation, duration, audio, sideways signature
```

## 7. Decide the fix path

Diagnosis ends with one of four decisions. Pick it from the evidence, tell the user which one and why,
**then act**.

| Class | Signal | Action |
|-------|--------|--------|
| **Configuration** | `401`, wrong workspace, missing key, wrong domain | Fix the configuration with the user. **No code change.** `references/deploy.md` |
| **External capacity** | `503 video_queue_full`, bare 503 "no available channel", `stuck_inference` after ~15 min | Report it, recommend a retry window or a version upgrade. **No PR** for upstream capacity |
| **Small, reproducible defect** | Wrong wording or missing i18n key, crash on empty/edge input, a missing back-compat default, a log that hides the real error, a doc that contradicts behaviour | Propose the fix, get agreement, then fix → verify → open a PR (§7.2) |
| **Large or unclear** | Pipeline redesign, retry-model changes, anything touching two or more tracks | Report with evidence and stop. No speculative refactor |

### 7.1 Confirm-first gate (hard rule)

**Diagnosis and fixing are separate steps.** Report the root cause, the proposed change and the blast
radius; wait for the user to agree; only then touch code. A deterministic failure that is not a code
defect gets a redacted report instead:

```bash
python3 scripts/report_issue.py <task_id>     # writes a report, prints a pre-filled issue URL
```

**The user submits it** — you never post on their behalf, and the report never contains a key or a
full prompt.

### 7.2 Small fix → PR

This is the only phase that clones the project. Repository:
`git@github.com:lcy362/agnes-video-generator.git` (a Gitee mirror is synced by CI; push to GitHub).

```bash
gh repo fork lcy362/agnes-video-generator --clone --remote   # origin = fork, upstream = project
cd agnes-video-generator
git fetch upstream && git switch -c fix/short-description upstream/main

# … make the change, following references/dev-standards.md …

bash scripts/preflight.sh                                    # mirrors CI, stops at the first failure
git add -A && git commit -m "fix(video): <english summary>"  # English commit messages are mandatory
git push -u origin fix/short-description
gh pr create --repo lcy362/agnes-video-generator --fill
```

`preflight.sh --full` also runs the mock regression (slow); add `--frontend` when you touched
`frontend/`. Run it from the project root, not from this skill directory.

Two rules that fail most PRs:

1. **English commit messages** — Conventional Commits prefix plus an English body.
2. **Changed `frontend/src/` → run `npm run build` and commit `static/`.** CI rebuilds and fails if
   `git status --porcelain static/` is non-empty.

| CI check | Command |
|----------|---------|
| Lint | `ruff check core/ web/ utils/ models/ scripts/` |
| i18n completeness | `python scripts/i18n_check.py` (`zh` and `en` both mandatory) |
| Tests + coverage ≥ 55% | `pytest tests/ --cov=core --cov=models --cov=utils --cov=web --cov-fail-under=55` |
| Frontend | `cd frontend && npm test && npm run build` |
| `static/` committed | `git status --porcelain static/` must be empty |
| Integration (no network) | `./scripts/run_mock_regression.sh` |

**Releasing is out of scope.** Version bumps and release notes involve a human review gate and belong
to the maintainer (upstream `docs/dev/release_process.md`).

If the change touches installation or startup, update `references/bootstrap-contract.md` in the same
PR — the exit-code table and the script must never drift apart.

## 8. Manual Mode

When the user asks you to improve the storyboard, narration, subtitles or a scene video, do the work
yourself — detect the waiting checkpoint, read `manifest.json`, edit the allowed fields, preview the
impact, then approve. Steps and acceptance criteria: `references/manual-mode.md`.

While a task runs: do not stop, resume or delete it just to look inside; never write an artifact whose
step is running (`409`); switch to manual mode instead of stopping.

## 9. Reference map

| Open this | When |
|-----------|------|
| `references/bootstrap-contract.md` | install paths, state machine, exit codes, lock, version gate |
| `references/deploy.md` | route details (npm / Docker / clone), workspace, key troubleshooting |
| `references/pipeline-selection.md` | choosing a type, cost, upload limits, switching mid-run |
| `references/progress.md` | step vocabularies, reporting template, stuck-task triage |
| `references/task-types.md` | per-type parameter tables and defaults |
| `references/manual-mode.md` | checkpoints, artifact editing, approve/regen |
| `references/artifacts.md` | artifact ids, cascade rules, write-back |
| `references/upstream-errors.md` | status codes, queue-full vs stuck inference, two-track retries |
| `references/resolution-orientation.md` | snapping, ratio protocol, the 9:16 rotation defect |
| `references/subtitle-timeline.md` | cue timeline, resume degradation, narration cleaning |
| `references/task-forensics.md` | diagnostics endpoint, error_logs, log prefixes, state machine |
| `references/upstream-probe.md` | raw curl + ffprobe re-probe recipes and the `video_id` trap |
| `references/dev-standards.md` | architecture, log prefixes, response format, back-compat rules |
| `references/frontend-i18n.md` | i18n contract, the build-and-commit rule |
| `references/testing.md` | unit tests, mock suite |
| `references/regression.md` | 14 scenarios, F/R/E acceptance |
| `references/workflow.md` | branch, commit, PR body, review etiquette, the hotfix path |

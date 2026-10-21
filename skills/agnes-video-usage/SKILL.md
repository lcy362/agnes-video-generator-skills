---
name: agnes-video-usage
description: Take the agnes-video-generator service from nothing to finished videos without cloning the project first - the skill installs it on demand into ~/.agnes-video, starts it on localhost:8765, walks the user through a free API key, picks the right pipeline (simple / creative / manuscript / anchor / poetry / image) for the request, reports progress step by step, and drives Manual Mode checkpoints by rewriting storyboards, narration, subtitles, scene videos or reference images before resuming. Use when the user says "install / set up agnes video", "generate a video with agnes", "make a creative / manuscript / poetry / digital-human video", "run it in manual mode", "improve the storyboard / narration / subtitles", or "check on my video task".
agent_created: true
version: 0.2.0
requires_service: ">=7.2.0"
---

# agnes-video-generator — usage

Everything below runs against `$AGNES_VIDEO_BASE` (default `http://127.0.0.1:8765`).
Changing the service's code → `agnes-video-contrib`; failures → `agnes-video-troubleshoot`.

**Do not clone the project and do not read its repository to get started.** The bootstrap
script owns installation; you own the conversation.

## 0. Bootstrap contract

```bash
python3 scripts/bootstrap.py probe  --json    # read-only: what exists, what is missing
python3 scripts/bootstrap.py install --yes --json   # once; then it also starts
python3 scripts/bootstrap.py start  --json    # idempotent; reuse if already running
python3 scripts/bootstrap.py verify --json    # readiness proof, costs no upstream quota
```

`verify` checks `/api/config`, `/api/voices`, `/api/tasks` and the index page. It is the evidence you
show the user that the machine is ready before a key exists — do not replace it with "the process
started".

Branch on the exit code, never on the text:

| Code | Meaning | What you do |
|------|---------|-------------|
| 0 | Ready | Create a task |
| 10 | Ready except no API key | §1 |
| 11 | Key rejected (usually domain mismatch) | §1, switch `com` / `cn_bak`, retry once |
| 20 | Needs consent (or nothing installed) | Explain cost, then `install --yes` |
| 30 | Environment unsupported | Report the missing runtime, stop |
| 40 | Installed below `requires_service` | Ask, then `install --force` |
| 50 | Port taken by something else | Ask for another `--port`; never pick one silently |

Rules:

- Run `probe` before anything else. If `service.reachable` is true, reuse it — do not reinstall,
  do not restart, the user may be watching the web UI.
- `install` prints what it will cost: ~2–5 minutes and several hundred MB under `$AGNES_HOME`
  (default `~/.agnes-video`). Get consent first. Everything lands in that directory; nothing is
  written into the current working directory, and the skill directory itself is read-only.
- A second run must be a no-op: same environment, no npm, no pip. If you see install output on a
  repeat run, stop and report it instead of pretending it is normal.
- Details, state machine, directory layout: `references/bootstrap-contract.md`.

## 1. Get a key (do this yourself, not "go read the docs")

The service is installed and verified before this step — that is deliberate. Show it is alive
(`GET /api/config`, `GET /api/voices`, the web UI) and say the only missing piece is a key.

Site and key must match, or every call returns `401`:

| Domain | API host | Where to get a key |
|--------|----------|--------------------|
| `com` (default) | `apihub.agnes-ai.com` | <https://platform.agnes-ai.com> |
| `cn` | `api.agnes-ai.cn` | the China site (needs a China-site key) |
| `cn_bak` | `apihub.agnes-ai.cn` | fallback; accepts global-site keys |

Hand the key over in the safest way available, in this order:

1. **Ask the user to paste it into `http://127.0.0.1:8765` themselves.** The key never enters your
   context or the shell history. Recommended.
2. `python3 scripts/bootstrap.py config-key --json` with the key on stdin (no echo, no argv).
3. `AGNES_API_KEY` — unattended/CI only. Environment keys cannot be bound per key and are skipped
   by auto-detection, so a `401` there means switching the global domain.

After the key arrives, bind and verify in one step (`config-key` does both):

```bash
POST /api/config/keys/detect     # bind each key to the domain it was issued on
GET  /api/models                 # cheap proof the key works (no generation)
```

Never echo the key, never write it to a file, never put it in a task payload.

## 2. Pick the pipeline from the request

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

## 3. Submit and report progress

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
- Same step with no progress for 10 minutes → check `/api/concurrency` and `upstream_errors` and
  explain why, instead of waiting silently or killing the task.
- There is **no WebSocket**; polling the same endpoint as the UI is not "taking over" the session.

## 4. Deliver with a predictable path

- Artifacts live under `$AGNES_HOME/workspace`; deliverable copies go to `$AGNES_HOME/outputs/<task_id>/`.
- If `AGNES_OUTPUT_DIR` is set, also copy the final file there (never overwrite — add `-1`).
- Always report the absolute path, plus `ffprobe` duration and resolution, and say which copy is which.

## 5. When it fails

1. Classify before acting: queue-full / `429` / timeout / `401` domain → fix and `resume` the **same**
   task; retrying must not create a new one.
2. Deterministic failure → collect evidence and prepare a report:

```bash
python3 ../agnes-video-troubleshoot/scripts/report_issue.py <task_id>
```

It writes a redacted report and prints a pre-filled GitHub issue URL. **The user submits it** — you
never post on their behalf, and you never put a key or a full prompt in it.

## 6. Manual Mode: you are the external agent

When the user asks you to improve the storyboard, narration, subtitles or a scene video, do the work
yourself — detect the waiting checkpoint, read `manifest.json`, edit the allowed fields, preview the
impact, then approve. Steps and acceptance criteria: `references/manual-mode.md`.

Rules while a task runs: do not stop, resume or delete it just to look inside; never write an
artifact whose step is running (`409`); switch to manual mode instead of stopping.

## Reference map

| Open this | When |
|-----------|------|
| `references/bootstrap-contract.md` | install paths, state machine, exit codes, lock, version gate |
| `references/deploy.md` | route details (npm / Docker / clone), workspace, key troubleshooting |
| `references/pipeline-selection.md` | choosing a type, cost, upload limits, switching mid-run |
| `references/progress.md` | step vocabularies, reporting template, stuck-task triage |
| `references/task-types.md` | per-type parameter tables and defaults |
| `references/manual-mode.md` | checkpoints, artifact editing, approve/regen |
| `references/artifacts.md` | artifact ids, cascade rules, write-back |

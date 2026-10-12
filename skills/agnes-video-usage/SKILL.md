---
name: agnes-video-usage
description: Take the agnes-video-generator service from nothing to finished videos - clone and configure the project, start the server on localhost:8765, pick among the six task types, submit a task and watch its progress alongside the web UI without disturbing it, and drive Manual Mode checkpoints by reading the artifact manifest and rewriting storyboards, narration, subtitles, scene videos or reference images yourself before resuming. Use when the user says "install / set up agnes video", "generate a video with agnes", "start the video service", "make a creative / manuscript / poetry / digital-human video", "run it in manual mode", "improve the storyboard / narration / subtitles", or "check on my video task".
agent_created: true
---

# agnes-video-generator — usage

Drive the service at `http://localhost:8765` (override with `AGNES_VIDEO_BASE`).
For changing the service's code see `agnes-video-contrib`; for failures see `agnes-video-troubleshoot`.

## 1. Establish the starting state first

```bash
curl -s -o /dev/null -w "%{http_code}\n" "$AGNES_VIDEO_BASE/" 2>/dev/null || echo "not reachable"
```

| State | What to do |
|-------|------------|
| **A. Nothing is installed** | Onboarding: probe the environment, pick a deployment route, clone, install, configure the API key, point the workspace at the folder the user wants, then run the four-layer verification. Full decision tree: `references/deploy.md` §0. |
| **B. Installed but not running** | Start it (`./start.sh`, or Docker/npm depending on how it was installed) and re-check. |
| **C. Running** | Go straight to §2. |

Onboarding rules:

- Ask the user for the API key — never invent one, never echo it back, never write it into a committed file.
  Free keys: <https://platform.agnes-ai.com>.
- `401` after configuration almost always means the key belongs to a different site than the configured
  domain (`com` / `cn` / `cn_bak`). See `references/deploy.md` §3 before touching anything else.
- Finish with `bash scripts/verify_deploy.sh` and report the result — a service that starts but fails
  verification is not ready.

## 2. Pick the task type

| User wants | Type | Endpoint | Checkpoints? |
|------------|------|----------|--------------|
| One prompt → one video (t2v / i2v / keyframes) | `simple` | `POST /api/tasks/simple` | no |
| An idea → story, storyboard, clips, narration, subtitles | `creative` | `POST /api/tasks/creative` | yes |
| Existing long text → per-paragraph visuals + one narration track | `manuscript` | `POST /api/tasks/manuscript` | yes |
| Talking-head presenter reading a script | `anchor` | `POST /api/tasks/anchor` | yes |
| A poem → per-line scenes + recitation + timed subtitles | `poetry` | `POST /api/tasks/poetry` | yes |
| A single still image (t2i / i2i) | image | `POST /api/image/generate` | no |

`simple` and image tasks have no pipeline and reject Manual Mode. Parameter tables, defaults and the
reference-image semantics that differ per type: `references/task-types.md`.

## 3. Submit a task and watch it without interfering

```bash
python3 scripts/agnes_task.py create --type creative \
  --field idea="A lighthouse keeper befriends a storm petrel" \
  --field video_width=768 --field video_height=1152
# -> {"ok": true, "task_id": "...", "dir_name": "..."}

python3 scripts/agnes_task.py status <task_id> --wait     # poll until a terminal state
python3 scripts/agnes_task.py download <task_id> -o out.mp4
```

There is **no WebSocket** — progress is polled from `GET /api/tasks/{task_id}`.

**Why this never disturbs the user:** the web UI and you read the same endpoint, backed by the same
`task_state.json`. There is no session to take over, no lock to acquire, and no risk of two clients
diverging. Point the user at `http://localhost:8765` and let them watch live in the browser while
you watch over the API.

Rules for staying out of the way:

- **Do not stop, resume or delete anything just to inspect it.** Reading state is free; interrupting
  a run is not.
- **Check `GET /api/concurrency` before submitting.** Concurrency is a weighted semaphore, so a new
  task may queue behind the user's running tasks — say so rather than silently queueing.
- **Never write to an artifact while its step is running.** `ai-modify` returns `409` for an active
  task for this reason. To change something mid-flight, use Manual Mode (§4), not a stop.
- **Report deltas, not snapshots** — step changes, progress jumps, new messages, terminal state.
  Repeating the full state on every poll wastes the conversation for no new information.
- Your local polling consumes **no** upstream quota. Only previews and actual generation do.
- Polling `status`/`progress` is the one thing you may read at will; `message` fields are for relaying
  to the user, and `current_message_key` + `current_message_params` are the ones to prefer when
  rendering text, so each UI language shows its own wording.

Want to see the LLM output before committing to a long run? `POST /api/creative/preview-script` and
`POST /api/manuscript/preview-split` create no task — but `preview-script` costs **three real LLM
calls**. Do not poll it.

## 4. Manual Mode: you are the external agent

The user's request "let an agent improve the storyboard / narration / subtitles" is addressed to
**you**. Do not hand back a prompt for someone else to run — do the work yourself.

```
scenes → references → videos → audio → subtitle → final
   ↑ detect which checkpoint is waiting, read its artifacts, improve them, approve, verify
```

The loop:

1. **Detect.** `GET /api/tasks/{id}` → a task is waiting for you when `status == "pending"` and
   `manual_config.current_checkpoint` is non-empty. In a list, that is `awaiting_user: true`.
2. **Decide where to pause** if the task is still running. Map the user's intent to checkpoints and
   call `POST /api/tasks/{id}/mode` with `mode=manual` and `pause_points` (`references/manual-mode.md` §1).
3. **Read what was produced.** `GET /api/tasks/{id}/checkpoints` for the group, and `manifest.json`
   (`working_dir`, plus `artifact_id` / `path` / `editable` / `schema_hint` per artifact) to know
   exactly which file and which fields you are allowed to touch.
4. **Improve it yourself** with your own file editing, using the acceptance criteria per checkpoint
   in `references/manual-mode.md` §5 — visual elements and continuity for storyboards, readability
   for narration, timing and line-breaking for subtitles, frame inspection for scene videos,
   dimensions for reference images. Change only the fields the request implies.
5. **Pre-warn, then commit.** Call `approve` once **without** `confirmed` to get the impact plan, tell
   the user which artifacts and downstream steps will be discarded, then call it again with
   `confirmed=true`. Use `regen` when the right answer is "re-run this checkpoint as-is".
6. **Verify the re-run, do not assume it.** Poll until the affected steps complete, then read the new
   artifacts back (and `ffprobe` them when media is involved). If a checkpoint is still ahead, loop
   to step 1.
7. At the end, download `final_video.mp4` and tell the user where it is.

Never: rename an artifact, edit while the step is running, or change fields outside the request.
Full endpoint table, cascade rules and the write-back format contract: `references/manual-mode.md`.

## 5. Rules that bite

- **`creative` produces a silent video by default** (`audio_enabled=false`) — turn it on explicitly
  if narration is wanted.
- **Reference-image semantics differ by type.** Creative aligns uploads *positionally* (image *i* →
  scene *i*); manuscript uses `reference_images_map`, an explicit paragraph-index array, and one image
  may serve several paragraphs.
- **`audio_add_tashkeel` (Arabic) affects the TTS input only.** Subtitles and narration text staying
  diacritic-free is intentional.
- **Never judge resolution or orientation from `perf_params`**, and never assume the requested pixel
  size was produced. Verify the file. Issues there: `agnes-video-troubleshoot`.

## 6. References

- `references/deploy.md` — §0 onboarding decision tree, deployment routes, key and domain configuration
- `references/task-types.md` — the six types, parameters, reference-image semantics, dry-run previews
- `references/manual-mode.md` — checkpoints, acceptance criteria, cascade rules, the agent procedure
- `references/artifacts.md` — task directory layout, `manifest.json`, formats, write-back

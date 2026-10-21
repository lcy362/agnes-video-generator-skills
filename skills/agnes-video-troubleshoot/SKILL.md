---
name: agnes-video-troubleshoot
description: Diagnose and collect evidence for agnes-video-generator failures - task failed or stuck, upstream HTTP 503 queue-full, 401 invalid token, timeouts, wrong output resolution, portrait video upside-down / sideways, subtitles out of sync, or subtitles degrading to heuristic timing after a resume. Covers the two-track retry model, the diagnostics endpoint and error_logs, direct upstream re-probing with curl plus ffprobe, and resume behaviour. Use when the user says "the task keeps failing", "it says 503 / queue is full", "invalid token", "generation timed out", "the video is sideways", "resolution is wrong", "subtitles do not match the audio", or "resume broke the subtitles".
agent_created: true
version: 0.1.0
---

# agnes-video-generator — troubleshooting

Diagnose a failed or suspicious run, produce **evidence**, and state a conclusion plus the next
step. Do not modify code here — that is the `agnes-video-contrib` skill.

## 1. Order of operations

```
1. Is this a service problem or an upstream problem?
   curl -s "$AGNES_VIDEO_BASE/api/health"
   curl -s "$AGNES_VIDEO_BASE/api/concurrency"
   → service down / overloaded → fix locally, stop here

2. Get the task's own story (no guessing)
   python3 scripts/diagnose_task.py <task_id>
   → state, step, message, error_traceback, upstream error logs, manifest, artifact health

3. Classify with the evidence, not the symptom
   references/upstream-errors.md        ← 503 / 429 / 401 / timeout / stuck_inference
   references/resolution-orientation.md ← wrong size, landscape vs portrait, sideways output
   references/subtitle-timeline.md      ← subtitles wrong after resume, cue timeline

4. Only if the service reports success but the artifact is wrong: re-probe upstream directly
   references/upstream-probe.md         ← raw curl + ffprobe recipes
```

## 2. The one-shot diagnosis script

```bash
python3 scripts/diagnose_task.py <task_id>              # summary + errors + artifacts
python3 scripts/diagnose_task.py <task_id> --json       # machine-readable, for further analysis
python3 scripts/diagnose_task.py --list --failed        # recent failures, newest first
```

It reads `GET /api/tasks/{id}`, `GET /api/tasks/{id}/diagnostics`, `GET /api/tasks/{id}/manifest`,
and the task's `error_logs/` entries, then prints what each one actually supports. It never infers
a cause the evidence does not carry.

## 3. Triage table

| Symptom | Most likely class | Evidence to collect |
|---------|-------------------|---------------------|
| `503` + `video_queue_full` | Upstream free-tier queue saturation (per-model pool) | body `code`; whether the same key submitted fine on another model |
| Bare `503`, no `code` | Upstream overload / no available channel | response body `message`; app version (pre-7.1.0 gave up too early) |
| `429` | Rate limit | Key ring size; whether another key was tried |
| `401` invalid token | Key bound to the wrong site domain | Which domain the key is configured for: `com` / `cn` / `cn_bak` |
| Stuck then `failed` after ~15 min, `error.message` "not finished after 15 minutes" | Upstream inference hard gate — waiting longer will not help | `internal_status`, `created_at`→`completed_at` delta |
| Task failed but the poll looked like HTTP 200 | Upstream reports failures **in the body** with HTTP 200 | body `status` + `error`, never the HTTP code alone |
| 404 while polling a just-submitted task | Not yet visible upstream (can take 10 min+ at peak) | Treat as intermediate; it is not a failure |
| Output size ≠ requested size | Upstream snapping / ratio protocol | `ffprobe` on the produced file — never `perf_params` |
| Portrait output is sideways | Known upstream 9:16 defect in the 2.5 series | `ffprobe` streams; no `Display Matrix` present |
| Subtitles misaligned after a resume | `sub_maker` recovery path | Whether the run resumed; whether cues were re-harvested |

## 4. Two rules that prevent most wrong conclusions

1. **HTTP status is not the verdict.** Upstream returns HTTP 200 on task failure, and its
   `error` field is an object `{code, message}` — treating it as a string corrupts messages.
   `progress` / `internal_progress` are contradictory in failure samples and must not be trusted.
2. **The produced file is the only truth for resolution and orientation.** `perf_params` is the
   internal inference size, not the container size, and any width/height-ratio check will happily
   pass a video whose pixels are rotated 90°.

## 5. Media-level checks

```bash
python3 scripts/check_media.py out.mp4
```

Reports container dimensions, rotation metadata, duration, audio presence, and whether the file
matches the known "portrait but lying on its side" signature. Also usable on a single scene file,
so a defect can be localised to one scene instead of the final composite.

## 6. Decide the fix path

Diagnosis ends with one of four decisions. Pick it from the evidence, tell the user which one and
why, **then act**.

| Class | Signal | Action |
|-------|--------|--------|
| **Configuration** | `401`, wrong workspace, missing key, wrong domain | Fix the configuration with the user. **No code change.** Point at `agnes-video-usage/references/deploy.md`. |
| **External capacity** | `503 video_queue_full`, bare 503 "no available channel", `stuck_inference` after ~15 min | Report it, recommend a retry window or a version upgrade. **No code change** — do not open a PR for an upstream capacity problem. |
| **Small, reproducible service defect** | Wrong wording or missing i18n key, crash on empty/edge input, a missing back-compat default, a log that hides the real error, a doc that contradicts behaviour | Propose the fix, get the user's agreement, then fix → verify → open a PR. See below. |
| **Large or unclear** | Pipeline redesign, retry-model changes, anything touching two or more tracks | Report with evidence and stop. Do not start a speculative refactor. |

### The confirm-first gate (hard rule)

**Diagnosis and fixing are separate steps.** Report the root cause, the proposed change and the blast
radius; wait for the user to agree; only then touch code. This matches upstream's own rule that a
regression or investigation records findings and does not change code until the user confirms.

### Handing off a small fix

Pass the `agnes-video-contrib` skill a dossier containing:

1. the symptom as the user described it, and the expected behaviour;
2. the evidence already collected (status codes, body codes, timestamps, `error_logs` entries,
   `ffprobe` output);
3. the suspected root cause with the file / symbol you believe is responsible, or "unknown";
4. the smallest change you believe fixes it, and how to verify it (which endpoint, which scenario);
5. the app version and deployment route, so the fix can be reproduced.

Also state when a user reports "it worked yesterday": collect timestamps and status codes before
theorising, and check whether a version upgrade is the real variable.

## 7. References

- `references/upstream-errors.md` — status codes, queue-full vs stuck inference, the two-track retry model
- `references/resolution-orientation.md` — snapping, ratio protocol, the 9:16 rotation defect
- `references/subtitle-timeline.md` — cue timeline, resume degradation, narration cleaning
- `references/task-forensics.md` — diagnostics endpoint, error_logs, log prefixes, state machine
- `references/upstream-probe.md` — raw curl + ffprobe re-probe recipes and the `video_id` trap

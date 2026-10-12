# Task forensics: state, diagnostics, logs

> Source anchor: upstream `web/routes/task_routes.py`, `models/task.py`, `core/task_manager.py`,
> `core/api/error_collector.py`, upstream `AGENTS.md` §6.1.
> Last verified: 2026-10-12.

## 1. Task state

`GET /api/tasks/{id}` returns the serialised task state plus `dir_name`, `active` and
`upstream_errors`.

| Field | Meaning |
|-------|---------|
| `status` | `pending` / `queued` / `running` / `completed` / `failed` |
| `current_step` | the active step key (e.g. `story`, `video_gen`) |
| `current_status` | `running` / `completed` / `failed` for the current step |
| `current_progress` | 0.0 – 1.0 |
| `current_message` | human-readable message, relative to `ui_language` |
| `current_message_key` + `current_message_params` | i18n key + interpolation values; prefer these when rendering |
| `error_traceback` | full traceback for environment-level failures |
| `manual_config` | `enabled`, `pause_points`, `current_checkpoint`, `approved_checkpoints`, `modified_artifacts`, `timeout_minutes` |
| `active` | whether a live pipeline exists in this process |

`active: false` while `status` is `pending`/`queued` is the **post-restart** signature: the run was
left behind by a service restart and needs `POST /api/tasks/{id}/resume`. That is not a failure.

`GET /api/tasks?status=running,queued&limit=20` filters and paginates; `awaiting_user` and
`current_mode` are computed there for Manual Mode tasks.

## 2. Diagnostics endpoint

`GET /api/tasks/{id}/diagnostics` returns:

```json
{
  "ok": true,
  "task_id": "abc123",
  "summary": {
    "task_type": "creative", "status": "failed", "current_step": "video_gen",
    "current_message": "…", "error_traceback": "…",
    "created_at": "…", "updated_at": "…"
  },
  "match_source": "exact | window | none",
  "error_logs": [ { "timestamp", "model_type", "api_method", "error_type",
                    "status_code", "error_message", "retry_count" } ]
}
```

`match_source` matters: `exact` means entries carried this `task_id`; `window` means they were
matched only by the task's time window (+2 h) and may belong to something else. Never quote
`window`-matched entries as this task's own errors without checking the timestamps.

Deliberately absent: prompt full text and `response_body`; `error_message` is truncated.

## 3. Error logs on disk

`error_logs/` (in the active workspace root or next to the server) records every failed model call:
prompt, error type, details. This is the **durable** record — the per-task aggregation exposed on the
task endpoint lives in memory only and is cleared by a restart.

## 4. Log prefixes worth grepping

| Prefix | Module | Typical meaning |
|--------|--------|-----------------|
| `[Pipeline]` / `[MultiScene]` | pipelines | generic pipeline flow, step boundaries |
| `[Simple]` `[Creative]` `[Manuscript]` `[Anchor]` `[Poetry]` | pipelines | task-type specific |
| `[EndFrame]` / `[Keyframes]` | pipelines | end-frame / keyframe handling |
| `[TTS]` / `[Subtitle]` / `[Voices]` | audio | synthesis, cue handling, voice compatibility |
| `[Compositor]` / `[Watermark]` | compositing | concat, scaling, overlays |
| `[AgnesVideo]` `[AgnesImage]` `[AgnesChat]` | API clients | upstream calls |
| `[RateLimiter]` | rate limiter | token bucket behaviour |
| `[KeyAuth]` | key manager | `401` attribution (records, never rotates) |
| `[UpstreamRotate]` | video output | 9:16 portrait rotation correction fired |
| `[ErrorCollector]` | error collector | persisted failures |
| `[Diagnostics]` | task routes | diagnostics endpoint matches |
| `[Artifacts]` / `[TaskManager]` | artifacts / persistence | registry, manifest, state writes |
| `[Workspace]` / `[Concurrency]` / `[Stop]` / `[Resume]` | server / app state | lifecycle |

Grep order that usually converges fast:

```bash
grep -n "\[AgnesVideo\]" server.log | tail -50
grep -nE "\[KeyAuth\]|\[UpstreamRotate\]|\[RateLimiter\]" server.log | tail -30
grep -n "<task_id>" server.log
```

## 5. Control endpoints

| Endpoint | Purpose |
|----------|---------|
| `POST /api/tasks/{id}/resume` | resume an interrupted or paused task; reuses cached `video_id`s |
| `POST /api/tasks/{id}/stop` | stop a running or queued task |
| `POST /api/tasks/sweep?age_days=7` | remove zombie task directories, protecting live ones |
| `GET /api/concurrency` | semaphore utilisation, running and queued tasks |
| `GET /api/health` / `GET /api/metrics` | health and rate-limit/concurrency metrics |

Concurrency is a **weighted** semaphore: a task's weight depends on its type, so "we are at the
limit" does not mean "N tasks are running". Check `current_weight` against `max_weight`.

## 6. Resume semantics

- The pipeline distinguishes a **checkpoint pause** (normal: the task is waiting for the user, the
  run returns without an error) from a **shutdown** (the state is persisted and the task must be
  resumed). Neither is a failure.
- On resume, completed steps are skipped, and their artifacts are reused. A skipped audio step
  triggers the cue re-harvest described in `subtitle-timeline.md`.
- Creative uses fine-grained resume points; the other multi-scene types use coarse whole-step
  skipping. So "resume regenerated everything" can be type-dependent rather than a bug.

## 7. Writing a report

Include: task id, task type, app version, the `summary` block, `match_source`, the relevant
`error_logs` entries with timestamps, `active`, and the artifact listing. Do not include prompts or
credentials — the diagnostics endpoint strips them for a reason.

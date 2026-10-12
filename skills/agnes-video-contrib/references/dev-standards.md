# Development standards

> Source anchor: upstream `AGENTS.md` §一 / §三 / §6.1–6.10 / §九, `docs/public/architecture.md`.
> Last verified: 2026-10-12.

## 1. Where things live

| Layer | Path | Put here |
|-------|------|----------|
| HTTP routes | `web/routes/` (nine routers) | new endpoints; keep the router's concern narrow |
| Shared route deps | `web/deps.py`, `web/app_state.py`, `web/helpers.py` | pipeline factories, concurrency, pure helpers |
| Pipelines | `core/pipelines/` | task-type behaviour; the four long-video types inherit `MultiScenePipeline` |
| Upstream clients | `core/api/` | Agnes HTTP calls, retry policy, rate limiting, key ring |
| Domain models | `models/task.py` | task types, state, request/response models |
| Media plumbing | `core/audio/`, `core/compositor/` | TTS, subtitles, ffmpeg work |
| Persistence | `core/task_manager.py`, `core/artifacts.py` | state files, artifact registry, manifests |
| Frontend source | `frontend/src/` | Vue components, composables, i18n — build output goes to `static/` |

**Back-compat alias modules — do not delete:** `core/pipeline.py`, `core/image_generator.py`,
`core/video_generator.py`, `core/audio/subtitle.py`, `core/compositor/concatenator.py`. They re-export
the real classes for older imports.

## 2. Adding an endpoint

1. Put it in the router that owns the concern; a new concern means a new file plus registration.
2. Accept `multipart/form-data` with `Form(...)` / `File(...)` for consistency with the creation routes.
3. Return `{"ok": true, ...}` on success.
4. Raise `HTTPException` with a **translated** message — see §3.
5. If it starts work, go through the existing concurrency and pipeline helpers in `web/deps.py`
   rather than spawning asyncio tasks directly.
6. Add the endpoint to upstream `docs/public/api.md` in the same PR. A new endpoint without
   documentation is an incomplete PR.

## 3. Responses, errors and languages

```python
return {"ok": True, "task_id": task_id, "dir_name": dir_name}
raise HTTPException(status_code=422, detail=translate("validation.video_duration_range", None, min=5, max=300))
```

- User-visible backend messages are **never hardcoded**. They go through the backend translation
  helper and the message key set, resolved per request from `X-Agnes-UI-Lang` →
  `Accept-Language` → `zh`, and per task from `state.ui_language` so a task keeps one language for
  its whole life even if the user switches the UI.
- Async pipelines emit progress as `current_progress` / `current_message`, and in v7.0+ also
  `current_message_key` + `current_message_params` so the frontend can render all 22 languages.
  Emit the key; do not pre-render a sentence.
- Validation errors use the existing key namespace (`validation.*`, `checkpoint.*`, `image.*`, …).

## 4. Logging

Use `logging.getLogger(__name__)` and keep the established prefixes, because support and debugging
greps depend on them:

| Prefix | Area |
|--------|------|
| `[Startup]` `[Resume]` `[Stop]` `[Workspace]` `[Concurrency]` `[Preview]` | server and app state |
| `[Pipeline]` `[MultiScene]` `[Simple]` `[Creative]` `[Manuscript]` `[Anchor]` `[Poetry]` | pipelines |
| `[EndFrame]` `[Keyframes]` | end-frame / keyframe handling |
| `[TTS]` `[Subtitle]` `[Voices]` | audio |
| `[Compositor]` `[Watermark]` | compositing |
| `[Image]` `[AgnesImage]` `[AgnesVideo]` `[AgnesChat]` | API and image flow |
| `[RateLimiter]` `[ErrorCollector]` `[Diagnostics]` `[KeyAuth]` `[UpstreamRotate]` | infrastructure |
| `[Artifacts]` `[TaskManager]` `[Screenwriter]` | persistence and LLM screenwriting |

Never log prompts, keys or full response bodies at info level.

## 5. Backward compatibility

Old `task_state.json` files must keep loading. That means:

- every new state field **needs a default**, so Pydantic fills it for old files;
- no renaming or repurposing of existing fields without a migration path;
- `parse_task_state()` falls back to the creative type when `task_type` is absent;
- config files written by older versions must still be readable.

A PR that breaks loading an old state file is a regression even if all tests pass.

## 6. Upstream calls

- **All retry decisions go through `core/api/retry_policy.py`** — the busy track and the fault track
  are defined there and nowhere else. Do not hand-roll sleeps or backoff in a client.
- Traffic goes through the token buckets (`core/api/rate_limiter.py`): the shared bucket for chat,
  images, uploads and polling, a separate bucket for video submission. Quotas scale with the number
  of keys and are rebuilt when the key set changes.
- `429` rotates to the next key and retries immediately; **`401` is recorded only** — no rotation, no
  retry, no pool change.
- Never log or return the upstream `error` object as a string; it is `{code, message}`.
- New upstream behaviour must be measured and written into
  `docs/dev/agnes_video_upstream_behavior.md` before it becomes a rule in code.

## 7. Artifacts

- Filenames and directory names are **fixed and stable** — external tools and the Manual Mode
  dependency graph match by name.
- New artifacts are declared in the registry (`core/artifacts.py`) together with their cascade
  relationships; otherwise Manual Mode impact calculations will silently miss them.
- File paths derived from user input go through the path-security check.

## 8. Configuration

- Environment variables are prefixed `AGNES_` and named for what they change.
- Any new variable gets a documented entry in `.env.example` with its default in the same PR.
- Local configuration lives in `config.json` with `0600` permissions and is always returned masked.

## 9. Style

Google-style docstrings, type annotations, `async`/`await` for IO, UTF-8 everywhere. Python 3.10+.
Frontend: ES6+, TypeScript, no new UI framework.

## 10. New features follow the documented flow

Requirement analysis → incremental PRD → plan document under `docs/plans/vX.Y/` → implementation.
For anything larger than a bug fix, do not start coding before the plan exists.

## 11. Things that get a PR rejected

- A Chinese commit message.
- `frontend/src/` changed without rebuilding `static/`.
- User-visible strings without i18n keys, or `zh` updated without `en`.
- A new state field without a default (breaks old state files).
- Hand-rolled retry logic outside `retry_policy.py`.
- Version numbers or release-note content.
- An undocumented endpoint or an undocumented `AGNES_*` variable.

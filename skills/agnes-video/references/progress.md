# Progress reporting

> Source anchor: `models/task.py` (`BaseTaskState`), `web/routes/task_routes.py` (`GET /api/tasks/{id}`,
> `GET /api/concurrency`), `frontend/src/steps.ts` (step keys), `frontend/src/composables/useProgress.ts`.
> Verified 2026-10-21 against upstream v7.2.0.

The user cannot see your tool calls. Every turn they get either a delta or silence — never a dump.

## 1. Where the data comes from

One endpoint, `GET /api/tasks/{id}` (no WebSocket in this project):

| Field | Use |
|-------|-----|
| `status` | `pending` / `queued` / `running` / `completed` / `failed` — the only terminal judge |
| `current_step` | step key of the moment (`story`, `video_gen`, …) |
| `current_status` | `running` / `completed` / `failed` for that step |
| `current_progress` | 0.0–1.0, already normalised across phases by the pipeline |
| `current_message`, `current_message_key`, `current_message_params` | prefer the key + params so the wording matches the user's UI language; fall back to the message |
| `step_*` (e.g. `step_story`) | `StepStatus` per step — how you know what is actually done |
| `active` | whether a pipeline is attached right now (false + `pending` = left over from a restart) |
| `upstream_errors` | status-code counts, for explaining slowness or failure |
| `manual_config.current_checkpoint` | non-empty = waiting for you |
| `created_at`, `updated_at` | elapsed time, stall detection |

Also useful: `GET /api/concurrency` → `current_weight`, `max_weight`, `queued_count`, `utilization`.

## 2. Step vocabularies (do not invent your own)

- `simple`: submit → video_gen
- `creative`: init → scene_config → image_analysis → story → character_ref → script →
  end_frame_prompts → end_frame_gen → video_gen → audio → subtitle → concatenate
- `manuscript`: split_text → scene_prompts → video_gen → audio → subtitle → concatenate
- `anchor`: generate_anchor → split_text → clip_prompts → clip_gen → audio → subtitle → concatenate
- `poetry`: build_scenes → video_generation → audio → subtitle → concatenation

## 3. Three layers of feedback

1. **Task level** — step x/y, name, elapsed, rough remaining.
2. **Step level** — which steps are done (`step_*`), what the current one is doing, per-scene counts
   when `current_message_params` carries them ("3 of 5 clips").
3. **Evidence level** — artifact paths (storyboards, clips, final), queue position, upstream error codes.

## 4. Cadence

- **Deltas only**: step change, ≥10% jump, new message, terminal state, new `upstream_errors` entry.
- **One wait ≤90 s per turn.** Long videos take 10–40 minutes; persist a snapshot to
  `$AGNES_HOME/tasks/<id>.json` and continue next turn (`status <id>` or `resume <id>`).
- **Explain stalls instead of idling**: same step and progress for 10 minutes → check
  `/api/concurrency` (queued?) and `upstream_errors` (`429` / `503`?) and tell the user the reason.
- Queueing is normal: "weight 3/4 with one task ahead, yours will start shortly."

Template (three lines, no more):

```
[creative 7/12 video_gen] 6m20s elapsed, 3 of 5 clips done
next: 2 clips → audio → subtitles → concatenate, roughly 8–12 min left
live view: http://127.0.0.1:8765
```

Terminal message: absolute output path + `ffprobe` duration/resolution; on failure, the failed step,
the error summary and the diagnostics entry point.

## 5. Forbidden

- Pasting `state.model_dump()` into the conversation.
- Inventing percentages when the data does not have them — say "step 7/12" instead.
- Using `current_message` where a key exists (multi-language users get the wrong language).
- Treating "no change" as "hung": check concurrency and upstream errors before stopping anything.

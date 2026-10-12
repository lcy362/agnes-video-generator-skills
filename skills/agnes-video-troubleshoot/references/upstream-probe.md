# Re-probing the upstream API directly

> Source anchor: upstream `docs/dev/agnes_video_upstream_behavior.md` §7.
> Last verified: 2026-10-12.

Use this when the service reports success but the artifact is wrong, or when you need to prove
whether a failure is ours or upstream's. It bypasses the service entirely and replays the same calls
the official demo makes.

## 1. Submit

```bash
export AGNES_API_KEY=...

# 2.5 series (ratio protocol)
curl -sS -X POST https://apihub.agnes-ai.com/v1/videos \
  -H "Authorization: Bearer $AGNES_API_KEY" -H "Content-Type: application/json" \
  -d '{"model":"agnes-video-2.5-flash","prompt":"...","mode":"text","seconds":"5","size":"720P","aspect_ratio":"9:16"}'

# v2.0 (pixel protocol)
curl -sS -X POST https://apihub.agnes-ai.com/v1/videos \
  -H "Authorization: Bearer $AGNES_API_KEY" -H "Content-Type: application/json" \
  -d '{"model":"agnes-video-v2.0","prompt":"...","width":768,"height":1152,"num_frames":121,"frame_rate":24}'
```

Passing v2.0 parameters (`width` / `height` / `num_frames`) to a 2.5 model returns HTTP 400
`"height is a forbidden field"`.

## 2. Poll — and use the right id

```bash
# 2.5 series: model_name is required
curl -sS "https://apihub.agnes-ai.com/agnesapi?video_id=<video_id>&model_name=agnes-video-2.5-flash" \
  -H "Authorization: Bearer $AGNES_API_KEY"

# v2.0: no model_name
curl -sS "https://apihub.agnes-ai.com/agnesapi?video_id=<video_id>" \
  -H "Authorization: Bearer $AGNES_API_KEY"
```

**The trap:** the submit response contains `id`, `video_id` and `task_id`, and for v2.0 they are
**not** the same value. Only `video_id` is guaranteed pollable; polling with `id` returns
`404 task not found`. Always resolve in the order `video_id` → `task_id` → `id`. Never assume the
format — for v2.0 `video_id` is a base64 routing key of variable length.

Other dead ends: `GET /v1/videos/<id>` always returns `400 task_not_exist`, and `GET /v1/videos`
(no id) does not exist (`404 Invalid URL`). `GET /v1/models` works.

## 3. Read the verdict from the body

```bash
curl -sS "…/agnesapi?video_id=<video_id>&model_name=<model>" -H "Authorization: Bearer $AGNES_API_KEY" \
  | python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("status"), d.get("internal_status"), d.get("error"), d.get("url"))'
```

Failures come back with **HTTP 200**; only the body tells you. `error` is an object
`{code, message}`. Ignore `progress` / `internal_progress`.

## 4. Inspect the artifact

```bash
curl -o probe.mp4 "<url from the response>"
ffprobe -hide_banner probe.mp4        # container size, streams, Display Matrix
```

Or use `scripts/check_media.py probe.mp4`, which also flags the 9:16 rotated-image signature.

## 5. What each observation proves

| Observation | Proves |
|-------------|--------|
| container size ≠ requested size | upstream snapping; not our bug |
| container portrait, no Display Matrix, composition landscape | the 9:16 defect; ours to correct or warn about |
| `status: failed` + `internal_status: stuck_inference` | the ~15 min hard gate; retrying is pointless |
| `503` + `code: video_queue_full` | model-pooled queue saturation; capacity, not code |
| bare `503` + `message` about channels | gateway capacity; also not code |
| submit `200` then `404` from `/agnesapi` for minutes | visibility window; keep waiting |

## 6. Record the evidence, do not conclude for the reader

Write down: timestamp (with timezone), model, requested parameters, HTTP status, body `status` /
`internal_status` / `error`, and the `ffprobe` output. One or two samples prove nothing about a
distribution — say "observed once" when that is the case.

## 7. Known unknowns (as of upstream's last measurement)

- Whether the `video_queue_full` queue is isolated per key — untested. The two-key test procedure is
  documented upstream; until it runs, do not claim that rotating keys bypasses a full queue.
- Whether the 15-minute gate counts from creation or from inference start (`started_at` was `null`).
- Artifact link expiry (`expires_at` was always `null`).

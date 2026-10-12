# Upstream errors and the two-track retry model

> Source anchor: upstream `docs/dev/agnes_video_upstream_behavior.md` (measured 2026-09-28),
> upstream `AGENTS.md` §6.2, `core/api/retry_policy.py`.
> Last verified: 2026-10-12. Conclusions marked "single observation" upstream are kept marked here.

## 1. Failures arrive with HTTP 200

The polling endpoint returns **HTTP 200 even when the task failed**; the verdict is in the body:

```json
{
  "status": "failed",
  "internal_status": "stuck_inference",
  "error": { "code": "500", "message": "ComfyUI internal error: inference not finished after 15 minutes" },
  "url": null,
  "progress": 0,
  "internal_progress": 100
}
```

A client that only checks the HTTP status will treat this as success. **Judge on body `status` +
`error` only.** `error` is an object `{code, message}` — treating it as a string corrupts the
message shown to the user.

## 2. Field reliability

| Field | Usable? | Note |
|-------|---------|------|
| `status` | yes | observed `pending` / `in_progress` / `completed` / `failed` |
| `error` | yes | object, see above |
| `url` | yes | final artifact address; `null` on failure; the hostname varies |
| `progress`, `internal_progress` | **no** | contradictory in failure samples (0 vs 100) |
| `started_at` | maybe `null` | cannot be used to compute queue/inference time |
| `perf_params` | **not for artifact checks** | internal inference size, not the container size |
| `expires_at` | observed `null` | artifact link lifetime unknown — download promptly |

## 3. The ~15 minute inference gate

One observed failure ran 953 s from `created_at` to `completed_at` with the message
"not finished after 15 minutes" and `url: null`. **Waiting longer will not produce a file.** Whether
the 15 minutes start at creation or at inference start could not be confirmed (`started_at` was
`null`).

Note the distinction: `video_queue_full` means "never got into the queue", while `stuck_inference`
means "queued, then the render hung". They look completely different to a user and deserve
different messages.

## 4. Submission-time errors

| HTTP | body `code` | Measured behaviour | Meaning |
|------|-------------|--------------------|---------|
| 503 | `video_queue_full` | 25 consecutive rejections over ~12 min for 2.5-flash, while the same key's v2.0 submissions went through | free-tier queue saturated, **pooled per model**; rejected submissions create no task and consume no quota — safe to retry |
| 503 | `fail_to_fetch_task` | one observation; a retry 25 s later succeeded | transient upstream fault, retryable |
| 503 | none (`message` only) | `No available channel for model … (distributor)` | gateway has no capacity/channel for that model; also creates no task. No queue semantics code |
| 429 | — | not reproduced in that round | rate limited; triggers key rotation |
| 401 | — | not reproduced in that round | key/domain mismatch |

**Bare 503s matter.** Before v7.1.0, 503 bodies without a recognised code fell into the generic 5xx
budget (5 attempts with linear backoff ≈ 5.5 min) and gave up while the queue was still saturated.
From v7.1.0 **all 503s share the busy track**. If a user reports `max retries (5) exceeded` next to
bare `HTTP 503: server error`, the first question is which version they are on.

The gateway (new-api) marks its own errors with a `(request id: …)` suffix; errors without that
suffix are task records passed through from the inference backend.

## 5. Two-track retry model

Every upstream call funnels through `core/api/retry_policy.py`, which knows exactly two tracks:

| | Busy track | Fault track |
|---|---|---|
| Signals | `429`, **all 503s** (including bare ones, no `code` needed), queue codes `video_queue_full` / `fail_to_fetch_task` | non-busy 5xx, timeouts, connection errors |
| First hop | **0 s — sits right against the rate limit** | — |
| Interval | fixed base (video 30 s + 0–30 s jitter, upload 30 s, image 20 s, chat 15 s) — deliberately "knock often" | `base × (n+1)`, growing — deliberately "knock rarely" |
| Cap | by **attempt count** (v7.2; previously a total-time budget): video `AGNES_VIDEO_BUSY_RETRY_ATTEMPTS` default 15, others `AGNES_BUSY_RETRY_ATTEMPTS` (defaults: image 15, upload 10, chat 20) | video 5, image 4, chat 3, upload 3 |
| Exhausted | queue codes raise a structured `AgnesQueueFullError`; 429 / bare 503 raise a generic technical error | generic technical error |

Why the first hop is 0 s: the token bucket already throttles the call, and the artificial wait and
the bucket wait are two ways to spend the same budget — stacking them would double the real
interval. On the busy track, retries stay at a fixed pace.

With multiple keys, a `429` rotates to the next key and retries **immediately** — no sleep, not
counted against the backoff.

Keys are pooled by `KeyRing` (`core/api/key_manager.py`); quotas scale with key count and the
limiter is rebuilt when keys change.

## 6. 401 invalid token

`401` is handled by **attribution only**: it is logged under the `[KeyAuth]` prefix in
`key_manager.py`, and the key is **not rotated, not retried, not removed from the pool**. Whether to
delete that key is the user's decision on the config page. If the user does nothing, the original
error keeps surfacing.

Root cause is nearly always a key bound to the wrong site domain — see
`agnes-video-usage/references/deploy.md` §3.

## 7. Polling design (do not "fix" it)

Polling is an adaptive probe loop, **not** part of the two-track model:

- interval starts at 20 s, +5 s every 5 polls, capped at 60 s
- `404` (`task not found`) is an **intermediate** state, not a failure: the task record can take
  ~20 s to become visible and, at peak, 10 minutes or more. It does not consume the consecutive
  failure budget and does not enter `error_logs`
- give up after 10 consecutive request failures
- overall timeout `AGNES_VIDEO_POLL_TIMEOUT` (default 1800 s)

A timeout is **not** a server-confirmed failure: on resume the stored `video_id` is reused.

## 8. Where the evidence lives

- `error_logs/` in the working directory: prompt, error type, details per failed call
- `GET /api/tasks/{id}/diagnostics`: summary plus sanitised error entries — see `task-forensics.md`
- Optional GA reporting: the service aggregates upstream errors per task in memory and exposes them
  as `upstream_errors` on the task detail endpoint. Memory only — restart clears it, so
  `error_logs/` remains the offline source of truth.

## 9. What to tell a user

1. Queue saturation and "no available channel" are **external capacity problems**, not bugs in the
   service. Say so plainly instead of opening a code change.
2. `stuck_inference` after ~15 minutes means retrying that task is pointless.
3. Bare 503 + `max retries (5) exceeded` on an older version → recommend upgrading rather than
   debugging.
4. Before theorising, collect: status codes, body codes, timestamps, and app version.

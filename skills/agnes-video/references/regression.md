# Large-version regression

> Source anchor: upstream `docs/dev/regression_test_plan.md` (§3 acceptance, §4 flow, §9–§12
> incremental), upstream `AGENTS.md` §七. Last verified: 2026-10-12.

Run this when a change is broad enough that unit tests cannot cover it — a version handover, a
pipeline-wide change, or before asking the maintainer to merge something large. It needs a real API
key and roughly an hour.

## 1. Core rules

1. **i18n gate first.** The runner executes `scripts/i18n_check.py` at start and **stops** if it
   returns 2 (missing). Complete the translations before re-running; never skip the gate.
2. **One round of tasks only.** Create exactly the scenarios in the matrix, one task each. Do not
   create extras.
3. **Do not change code during a run.** Record problems in the report; fix only after the user
   confirms (the same gate the diagnosis phase applies).
4. **Record the concrete reason for every failure** — HTTP status, error message, timeout duration.
5. **Resume unexplained failures.** If the cause is unclear (timeout, transient API fault), finish
   with `--resume` instead of skipping. Do not mark something "passed" by omission.

## 2. Scenario matrix (14)

| ID | Type | Scenario |
|----|------|----------|
| S1 | simple | keyframe animation |
| C1 | creative | reference image + keyframes, no narration |
| C2 | creative | end frame generated from the reference image + keyframes, no narration |
| C3 | creative | subtitles + narration + keyframes |
| C4 | creative | user-uploaded storyboard images + keyframes |
| C5 | creative | Arabic creative with tashkeel (subtitles / `narration.txt` must contain no harakat) |
| M1 | manuscript | short text + narration |
| M2 | manuscript | short text + custom subtitles |
| M3 | manuscript | short text + per-paragraph reference images (`reference_images` + `reference_images_map`) |
| M4 | manuscript | split preview (`preview-split` / `preview-script`, **creates no task**) |
| A1 | anchor | digital human + post-stitched audio |
| A2 | anchor | digital human + model audio |
| P1 | poetry | recitation + subtitles |
| I1 | image | text-to-image |

## 3. Running it

```bash
python scripts/regression_runner.py --auto-start              # full run
python scripts/regression_runner.py --resume --auto-start     # resume an interrupted run
python scripts/regression_runner.py --quick                   # only verify existing artifacts

python scripts/scene_runner.py --scenario C3                  # one scenario (avoids polling from the main agent)
python scripts/scene_runner.py --endpoints                    # endpoint checks only
python scripts/scene_runner.py --list / --validate-only       # inventory / validate without running
```

Notes that save a lot of pain:

- `scene_runner.py` runs one scenario in a subprocess and prints JSON, so the driving agent does not
  have to hold minutes of polling in its context. Prefer it over driving the API by hand.
- Set `AGNES_REGRESSION_WORKING_DIR` to keep regression output in a scratch directory instead of the
  user's real workspace.
- `POST /api/cleanup-regression` removes regression artifacts afterwards.

## 4. Acceptance checklist

### Final artifacts (§3.1)

| ID | Check | Automated |
|----|-------|-----------|
| F1 | `final_video.mp4` exists and is non-empty | yes |
| F2 | duration > 0 | yes |
| F3 | resolution matches the request | yes — **read the produced container only; never `perf_params`**. v2.0 compares absolute pixels with ±15% tolerance (standard tiers are honoured, non-standard ones snap); the 2.5 series compares **aspect ratio** with ±15% because its absolute pixel count is not preserved (`3:4` really is 834×1112) |
| F4 | audio track present with speech | yes — audio stream detection plus ASR |
| F5 | subtitles visible in the picture | **manual** — watch it |
| F6 | subtitle text matches the source | yes — fuzzy ASR match (> 30%) |
| F7 | total duration matches expectation ±15% | yes |

### Resume artifacts (§3.2)

| ID | Check |
|----|-------|
| R1 | `task_state.json` is valid JSON |
| R2 | `task_type` is correct |
| R3 | completed steps are marked `completed` (anchor skips steps that do not apply to its `audio_source`) |
| R4 | `final_video_file` path exists |
| R5 | each `task.json` exists and carries a `video_id` |
| R6 | each `curl.sh` exists and is a valid query command |
| R7 | audio files exist |
| R8 | subtitle files exist |
| R9 | the combined narration audio exists and is non-empty |
| R10 | the combined subtitle file parses and has more than one entry |

### Endpoints (§3.3)

E1 `GET /` returns 200 with the tabs · E2 `GET /api/config` · E3–E5 and E10 parameter validation for
simple/creative/manuscript/anchor (`200`/`422`) · E6 `GET /api/tasks` lists the types · E7 task detail
returns `task_type` · E8 resume (`200` or a sensible 4xx) · E9 stop · E11 `GET /api/config/keys`
returns `key_count`/`source` with no plaintext key · E12 saving keys rebuilds the key ring and limiter ·
E13 `DELETE /api/tasks/{id}` (400 while running).

### Incremental suites

The plan also carries per-version sections with their own acceptance tables — do not assume the ones
above cover them: §9 Manual Mode (3 scenarios + extra endpoints), §10 the feedback module (frontend
closed loop + diagnostics endpoint), §11 upstream reliability hardening (unit tests plus manual
probes), §12 ffmpeg/ffprobe call consolidation (unit tests plus a no-ffprobe environment check).

## 5. Reports

Three files are written: `docs/dev/regression_report.json`, `regression_report.md` and
`regression_issues.md`. Treat the report as the deliverable — a run without a readable report did not
happen.

## 6. After the run

- **Recoverable** failures (timeout, API fault, network) → `--resume` and retry.
- **Not recoverable** (HTTP 400, prompt errors) → record the exact reason, skip, and wait for the user
  before touching anything.
- Anything that looks like a service defect goes through the troubleshooting skill's fix-path decision
  — and only becomes a code change after the user agrees.

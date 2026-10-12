# Manual Mode: the agent procedure

> Source anchor: upstream `docs/public/manual_mode_guide.md`, `docs/dev/artifact_standard.md`,
> `models/task.py` (`ManualConfig`), `web/routes/video_routes.py` checkpoint endpoints.
> Last verified: 2026-10-12.

You are the external agent. When the user says "improve the storyboard", "polish the narration" or
"fix the subtitles", **you** open the artifacts, change them and approve the checkpoint. There is no
prompt to hand over to somebody else.

```
scenes → references → videos → audio → subtitle → final
```

`simple` and image tasks have no pipeline and no checkpoints — a Manual Mode request against them is a
mistake, not a bug.

## 1. Enabling it, and choosing where to pause

- **At creation:** `execution_mode=manual` plus `pause_points` (a JSON array). An empty `pause_points`
  with `manual` means *every* checkpoint. A non-array value or an invalid mode is rejected with 422.
- **Mid-run:** `POST /api/tasks/{id}/mode` with `mode=manual` or `mode=auto`.
  - auto → manual: the task suspends at the next safe point and enters the checkpoint page.
  - manual → auto: pause points are cleared and the task runs to completion immediately.
  - Idempotent: an already-paused task returns `changed: false`.

**Valid `pause_points` values** (12 in total; anything else is rejected with 422):

```
image_analysis  story  script  character_ref  end_frame_prompts  end_frame_gen
scenes  references  videos  audio  subtitle  final
```

Which of them can actually fire depends on the task type, because a checkpoint fires when the
matching **step** completes:

| Task type | Checkpoints that occur |
|-----------|------------------------|
| `creative` | fine-grained set: `image_analysis` → `story` → `script` → `character_ref` → `end_frame_prompts` → `end_frame_gen` → `videos` → `audio` → `subtitle` → `final` |
| `manuscript` / `anchor` / `poetry` | coarse set: `scenes` → `references` → `videos` → `audio` → `subtitle` → `final` |

So `references` on a creative task is *accepted but never reached* (creative produces its images in
`character_ref` / `end_frame_gen` instead). Passing a valid-but-unused checkpoint fails silently —
pick from the row that matches the task type.

**Choose pause points from what the user wants to control**, not "all of them" by default:

| User wants to control | Pause at (coarse types) | Pause at (creative) |
|-----------------------|-------------------------|---------------------|
| The story / overall direction | `scenes` | `story`, `script` |
| Character and style consistency | `references` | `character_ref` |
| The look of each shot | `scenes` | `script`, `end_frame_prompts` |
| One specific shot's motion or quality | `videos` | `videos` |
| The spoken script | `audio` | `audio` |
| Reading speed, line breaks, timing | `subtitle` | `subtitle` |

Pausing everywhere costs the user a review round trip per checkpoint — on creative that is up to ten
stops. Pause only where a change is expected, and tell the user which checkpoints you selected and why.

## 2. Detecting a waiting task

A task is waiting for you when `status == "pending"` **and** `manual_config.current_checkpoint` is
non-empty. This is derived from local state only:

```bash
python3 scripts/agnes_task.py status <task_id>        # prints state + current checkpoint + awaiting flag
python3 scripts/agnes_task.py list --awaiting         # everything currently waiting on a human/agent
```

Do not stop or resume anything to "look inside" — reading is enough, and stopping would discard the
user's ability to keep watching in the browser. If the user is mid-run and wants you to take over,
switch the mode (§1) instead.

## 3. Read what was produced, and know what you may touch

```bash
GET /api/tasks/{id}/checkpoints                 # checkpoint groups with their artifacts
GET /api/tasks/{id}/checkpoints/{cp}            # just this checkpoint
GET /api/tasks/{id}/manifest                    # manifest.json (structured)
GET /api/tasks/{id}/manifest.md                 # MANIFEST.md (human-readable)
```

From the manifest, per artifact:

| Field | Why it matters to you |
|-------|----------------------|
| `working_dir` | the absolute task directory — every path below is relative to it |
| `artifact_id` | the id you pass to `approve` / `regen` / `ai-modify` / `upload` |
| `path` | the file to open and edit |
| `editable` | text/JSON/SRT are editable; image/video/audio are replaced, not edited |
| `schema_hint` | human-readable description of the fields — read this before parsing JSON |
| `generated_by_step` | which step produced it, i.e. what will re-run if you change it |

Read the file itself before deciding anything. Do not infer content from the artifact name.

## 4. Editing rules

1. Edit **in place under the same filename**, or upload a replacement via
   `POST /api/tasks/{id}/artifacts/{artifact_id}/upload`.
2. Formats: UTF-8 without BOM · JSON `indent=2` + `ensure_ascii=False` · standard SubRip for SRT with
   contiguous sequence numbers · PNG for images (jpg/png/webp accepted on upload) · MP4 H.264+AAC for
   video · MP3 for audio.
3. Change **only** the fields the request implies. Rewriting a storyboard must keep the scene count
   and every `narration_text` unless the user asked otherwise.
4. Never rename an artifact — the dependency graph matches by name.
5. Never edit while the producing step is running (`ai-modify` returns 409 for an active task; direct
   file edits race the pipeline).
6. Show the user what you changed before approving, in their terms — not a diff dump.

## 5. Acceptance criteria per checkpoint

These are the quality bar you edit against. Use the user's language and the original content's
language; do not translate unless asked.

**`scenes` — storyboard (`script.json`)**
Keep the JSON structure, the scene count, and every `narration_text` and `duration`. Strengthen only
`scene_prompt` / `end_frame_prompt`: name the subject, the composition, the camera movement
(push / pull / pan / track), the lighting and colour mood, and keep visual continuity with the
neighbouring scenes (same character appearance, same palette). Roughly one sentence each — long
prompts do not buy more coherence.

**`references` — reference image (`character_reference.png`)**
Subject centred, background de-emphasised, consistent aspect with the target video, output 768×1152
PNG at high quality unless the task uses another ratio. Print the resulting dimensions so the user can
confirm.

**`videos` — scene clip (`scene_{i}/video.mp4`)**
Inspect before touching: extract frames at the first seconds into `scene_{i}/frames/` and look at
them. If the shot is acceptable, say "no change needed" — silence is a valid outcome. If it needs work
(crop, colour, trim), write `video_fixed.mp4`, print the exact ffmpeg command, keep the original
aspect ratio, and do not re-encode audio. One bad scene is not a reason to regenerate the others.

**`audio` — narration text (`combined_narration.txt` for creative, `full_narration.txt` for
manuscript/anchor)**
Keep the meaning and information content, stay within roughly ±10% of the original length, prefer
short spoken sentences over written connectives, keep the paragraph count and order (one paragraph per
scene), and target the original duration at about 4 characters per second for Chinese. Write plain
text back to the same file; the service regenerates audio and subtitles from it.

**`subtitle` — subtitles (`full_subtitle.srt`)**
Take the real audio duration —
`ffprobe -v error -show_entries format=duration -of csv=p=0 <task_dir>/combined_narration.mp3` — and
ensure no cue ends past it. No overlaps (a 50 ms gap is allowed), every cue ≥ 0.3 s, at most ~18
characters per line for Chinese or two lines maximum, English broken at word boundaries, sequence
numbers contiguous, timestamps `HH:MM:SS,mmm`.

## 6. Approve — pre-warn first

| Endpoint | Purpose |
|----------|---------|
| `GET /api/tasks/{id}/checkpoints/{cp}/impact` | what would be deleted and re-run |
| `POST /api/tasks/{id}/checkpoints/{cp}/approve` | confirm and continue |
| `POST /api/tasks/{id}/checkpoints/{cp}/regen` | re-run this checkpoint as-is |
| `POST /api/tasks/{id}/checkpoints/{cp}/ai-modify` | let a model rewrite one artifact |
| `POST /api/tasks/{id}/artifacts/{artifact_id}/upload` | persist a replacement file |

`approve` takes `modified_artifact_ids` (JSON array), `param_updates` (JSON) and `confirmed`:

- **without** `confirmed=true` it only computes the impact plan and changes nothing — always call it
  this way first, and tell the user what will be discarded;
- with `confirmed=true` it deletes the affected artifacts, resets those steps, marks the checkpoint
  approved and resumes.

`regen` is equivalent to approving with every artifact of the checkpoint marked modified.

Cascade: editing narration re-runs audio → subtitle → final; editing a visual description re-runs
references → videos → final; editing one scene video re-runs audio → subtitle → final while keeping
the other scene videos; editing subtitles re-runs only the final composite. Saying this out loud
before approving is what makes the cost predictable for the user.

`ai-modify` (`artifact_id` + `user_request`) returns rewritten content for text/image artifacts
**without** persisting it, and returns 400 for video/audio. Use it only when a model-written draft is
genuinely useful; prefer doing the edit yourself, then `upload` and `approve`.

## 7. Verify the re-run, then continue

Approval is not the end of your job:

1. Poll `GET /api/tasks/{id}` until the affected steps report completed.
2. Read the regenerated artifacts back — the file changed, and `ffprobe` still reports sane
   duration / size / audio when media is involved.
3. If another checkpoint is ahead in `pause_points`, go back to §2.
4. Otherwise download `final_video.mp4` and tell the user where it is.

## 8. When the change does not take

- The user rejects your edit → restore the original from git-less backup you made before editing, or
  re-`regen` the checkpoint.
- The re-run produced the same problem → stop editing artifacts; this is a service or upstream defect,
  which is the `agnes-video-troubleshoot` skill's job.
- Use the checkpoint page's "Report a problem" entry (task id, checkpoint, handling method,
  before/after diff, `checkpoint.json`, error log) to produce a report, then add expected result,
  actual result and reproduction steps.

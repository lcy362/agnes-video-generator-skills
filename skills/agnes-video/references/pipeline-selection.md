# Picking the pipeline

> Source anchor: `models/task.py` (request models, step fields), `frontend/src/steps.ts` (step keys),
> `docs/public/usage.md`. Verified 2026-10-21 against upstream v7.2.0.

Six entry points, one right answer per intent. Choose by **what the user has and what they expect to
see**, not by which model sounds newer.

## 1. Four questions, in order

| # | Question | Consequence |
|---|----------|-------------|
| Q1 | What is the source material: one sentence / a long text / a poem / a person's photo / a single image? | `simple` / `manuscript` / `poetry` / `anchor` / image |
| Q2 | Does it need multiple scenes with continuity (storyboard, transitions, a plot)? | yes + no source text → `creative`; yes + source text → `manuscript` |
| Q3 | Does it need narration and subtitles? | long types include both by default; `simple` has neither |
| Q4 | Must the user upload images (first/last frame, character, custom storyboards)? | see §4 — the task script cannot upload |

Stop asking as soon as one answer decides it. Anything inferable from the request should not become
a question.

## 2. Decision table

| Request | Type | Key fields | Typical wall time | Symptom of the wrong choice |
|---------|------|-----------|-------------------|-----------------------------|
| "a 5–10 s shot" | `simple` t2v | `prompt` | 1–5 min | `creative` → 20 min wasted plus unwanted narration |
| "a story / short film with storyboards" | `creative` | `idea`, `scene_count`, `scene_durations` | scenes × 3–8 min | `simple` → one shot, the plot never lands |
| "put my article on screen" | `manuscript` | `manuscript_text` | paragraphs × 3–8 min | `creative` → the text gets rewritten instead of narrated verbatim |
| "digital human / talking presenter" | `anchor` | character image + script + audio mode | segments × 3–8 min | `creative` → no character consistency |
| "turn this poem into a video" | `poetry` | the poem, voice | lines × 3–8 min | `manuscript` → line breaks and rhyme are lost |
| "just generate an image" | image | `prompt`, size | < 1 min | a video task burns quota for nothing |

State the choice and the estimate **before** submitting, and offer the cheaper alternative. One
sentence now is cheaper than a rerun later: "this fits `creative`, about 15–25 minutes; if you only
want one shot, `simple` takes a few minutes."

## 3. Scale and cost

- `scene_count ≈ target duration ÷ per-scene duration` (default 5 s per scene). Above 8 scenes, warn:
  40+ minutes total and every scene is an independent failure point.
- Verify the path with a short `simple` task first; never use a long pipeline as the first smoke test.
- Changing your mind mid-run: `stop` the task and create a new one of the right type. Do not `resume`
  a `creative` task into a `simple` result, and say that already-generated clips will not be reused.

## 4. Capability limits to check before promising anything

- `agnes_task.py` does not upload files. `anchor` (character image), `i2v` / `ti2vid` / `keyframes`
  (first/last frames) and custom storyboard images need either `curl -F` against the upload endpoint
  or the user uploading in the web UI. Say so instead of inventing a parameter.
- External asset mode (v7.6, e.g. Jimeng collaboration) is for artifacts produced elsewhere and then
  imported (`POST /api/tasks/{id}/artifacts/import`). It is not part of this selection table; see
  `manual_mode_guide.md` when the user brings their own clips.
- Manual Mode is only worth turning on when the user wants an agent to rewrite artifacts. Otherwise
  stay on auto and avoid pointless pauses.

## 5. Parameter defaults worth knowing

| Type | Default that surprises people |
|------|-------------------------------|
| `simple` | mode must be explicit (`t2v` when no image is involved) |
| `creative` | `duration_source=manual` with `scene_count=3`; switch to `prompt` to let the LLM size the scenes |
| `manuscript` | splitting is by paragraph; very long paragraphs become long, static scenes |
| `anchor` | `audio_mode=post_stitch` (TTS after stitching) vs `model` (audio carried by the model) |
| `poetry` | the original line becomes narration, the scene description becomes the video prompt |

Per-type field tables: `task-types.md`.

# The six task types, parameters and previews

> Source anchor: upstream `docs/public/api.md`, `docs/dev/pipeline_products.md`, upstream `AGENTS.md` §一.
> Parameter defaults verified against `web/routes/task_creation_routes.py` and `web/routes/image_routes.py`
> on 2026-10-12.

All endpoints accept `multipart/form-data` and return `{"ok": true, "task_id": "...", "dir_name": "..."}`.
There is no API-key form field — the server uses its configured key.

## 1. What each type actually does

| Type | Flow | Narration | Subtitles | Manual Mode |
|------|------|-----------|-----------|-------------|
| `simple` | your prompt → submit → watermark | none | none | no |
| `creative` | idea → LLM story → LLM storyboard (+ end-frame prompts) → images → per-scene clips → TTS narration → cue-aligned subtitles → concat | one LLM-written block | yes | yes |
| `manuscript` | your text → paragraph split → LLM visual prompt per paragraph → clips → one TTS track over your text → subtitles | your own text | yes | yes |
| `anchor` | digital-human image/loop prompt → looping i2v clip(s) → narration or the model's own audio → subtitles | your script | yes | yes |
| `poetry` | poem → LLM scene split (original lines = narration, scene text = video prompt) → per-line clip + TTS + timed subtitles → concat | the poem's own lines | yes | yes |
| image | one t2i / i2i call, saved to the task directory | — | — | no (no pipeline at all) |

Creative, manuscript, anchor and poetry all inherit the same multi-scene base class, so the stage
order and progress bands are identical:

| Stage | Progress | Notes |
|-------|----------|-------|
| build scenes | 0.00 → 0.15 | storyboard / paragraph split / poem split |
| reference images | 0.15 → 0.30 | skipped by types that do not need it |
| video generation | 0.30 → 0.75 | the long stage |
| narration | 0.75 → 0.85 | returns the cue source used by subtitles |
| subtitles | 0.85 → 0.90 | depends on narration |
| composite | 0.90 → 0.98 | then watermark → 1.00 |

## 2. Parameters

### `POST /api/tasks/simple`

| Field | Default | Notes |
|-------|---------|-------|
| `prompt` | required | used verbatim, no LLM rewriting |
| `mode` | `t2v` | `t2v` / `i2v` / `ti2vid` / `keyframes` |
| `duration` | `5` | seconds |
| `video_width` / `video_height` | `768` / `1152` | portrait by default |
| `video_size` | `720P` | resolution tier for the 2.5-series protocol |
| `seed`, `negative_prompt`, `system_prompt` | — | passthrough |
| `reference_image` | — | file upload, drives `i2v` / `ti2vid` |
| `end_frame_image` | — | file upload, drives `keyframes` |

### `POST /api/tasks/creative`

| Field | Default | Notes |
|-------|---------|-------|
| `idea` | required | the story seed |
| `creative_name`, `style` | — | |
| `chaining_mode` | `keyframes` | scene-to-scene continuity strategy |
| `video_width` / `video_height` | `768` / `1152` | |
| `duration_source` | `manual` | `manual` or `prompt` (LLM decides lengths) |
| `scene_count` | `3` | |
| `uniform_duration` | `true` | else use per-scene values |
| `scene_durations_json` | `[5,5,5]` | |
| `reference_image` | — | optional single character reference |
| `end_frame_images` | — | uploads, used with `use_custom_end_frames` |
| `use_custom_end_frames` | `false` | |
| `generate_end_frames_from_ref` | `true` | derive end frames from the reference image |
| `scene_reference_images` | — | uploads, **positional**: image *i* → scene *i* |
| `audio_enabled` | **`false`** | creative is silent unless you turn this on |
| `audio_voice`, `audio_rate`, `audio_lang`, `audio_add_tashkeel` | `zh-CN-XiaoxiaoNeural`, `+0%` | |
| `subtitle_enabled` | `true` | |
| `subtitle_style_mode` | `fixed` | `fixed` or `llm` (LLM generates `subtitle_styles.json`) |
| `subtitle_font` / `_color` / `_fontsize` / `_position` / `_stroke_color` / `_stroke_width` / `_bg_color` | `STHeitiMedium.ttc`, `white`, `48`, `bottom`, `black`, `2`, `black@0.5` | |
| `execution_mode` | `auto` | `manual` enables checkpoints |
| `pause_points` | `""` | JSON array; empty + `manual` = every checkpoint |

### `POST /api/tasks/manuscript`

| Field | Default | Notes |
|-------|---------|-------|
| `manuscript_text` | required | split into paragraphs by the service |
| `style` | — | |
| `reference_images` | — | uploads |
| `reference_images_map` | `[]` | JSON array of paragraph-index arrays, **aligned with the uploads** |
| `video_width` / `video_height` | `768` / `1152` | |
| `video_duration` | `10` | per paragraph |
| `audio_enabled` | **`true`** | |
| `subtitle_*`, `execution_mode`, `pause_points` | as creative | |

Reference-image semantics: `reference_images_map` is an array of arrays; the *i*-th upload serves
the paragraph indices listed in `reference_images_map[i]`, so one image may drive several
paragraphs. The paragraph count is only known after splitting; out-of-range indices log a warning
and are ignored (they do **not** raise 422).

### `POST /api/tasks/poetry`

| Field | Default | Notes |
|-------|---------|-------|
| `poem_text` | required | |
| `user_scene_prompts_json` | `[]` | overrides the LLM's per-scene prompts |
| `video_duration` | `30` | **valid range 5–300** |
| `duration_source` | `manual` | `manual` or `prompt` |
| `scene_count`, `uniform_duration`, `scene_durations_json` | `3`, `true`, `[5,5,5]` | |
| `audio_rate` | `-15%` | recitation is slower by default |
| others | as creative/manuscript | |

### `POST /api/tasks/anchor`

| Field | Default | Notes |
|-------|---------|-------|
| `script_text` | required | the presenter's script |
| `anchor_prompt`, `anchor_reference_image` | — | persona description / uploaded face |
| `audio_source` | `post_stitch` | `post_stitch` = TTS added after stitching; `model` = the model's own audio |
| `video_width` / `video_height` | `768` / `1344` | taller than the other types |
| `subtitle_fontsize` | `42` | |
| others | as creative | |

With `audio_source=model`, the TTS step is skipped entirely.

### `POST /api/image/generate`

| Field | Default | Notes |
|-------|---------|-------|
| `prompt` | required | max 5000 chars, non-empty |
| `size` | `1024x1024` | validated; an invalid value returns 422 |
| `negative_prompt`, `system_prompt` | — | |
| `reference_image` | — | upload → i2i instead of t2i |

This route has no pipeline and no checkpoints.

## 3. Dry-run previews

Neither of these creates a task; both are useful before committing to a long run.

| Endpoint | Returns | Cost |
|----------|---------|------|
| `POST /api/creative/preview-script` | story + storyboard + narration text | **3 real LLM calls** |
| `POST /api/manuscript/preview-split` | paragraph split + estimated durations | no LLM, still counts against the concurrency limit |

Both share an in-process concurrency cap of 2 and return `429` with `Retry-After: 5` beyond it.
`preview-script` also accepts `content_lang` ∈ {`ar`,`en`} and `add_tashkeel`.

## 4. Arabic diacritics

`audio_add_tashkeel` (creative / manuscript) adds tashkeel to the narration **sent to TTS only**,
to improve pronunciation. Subtitles and the exported narration text deliberately stay
diacritic-free — do not "fix" that by propagating it to the artifacts.

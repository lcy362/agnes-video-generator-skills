# Subtitle timeline and narration

> Source anchor: upstream `docs/dev/pipeline_products.md` §1.1–1.5 and §7,
> `core/pipelines/__init__.py` (`generate_subtitles_common`, `_recover_sub_maker`).
> Last verified: 2026-10-12.

## 1. The timeline's source of truth

The subtitle timeline comes from EdgeTTS `SubMaker.cues` — the per-word `WordBoundary` timestamps of
the synthesised audio, i.e. the same axis the audio lives on. The final video runs continuously from
0 (`final_dur = max(video_dur, audio_dur)`), so **cue time is display time and `offset = 0`**.

`generate_cue_aware_srt` attributes cues to scenes in two ways:

- **Strategy A (text anchoring):** normalise and concatenate each segment's text, compute character
  ranges, and assign each cue by its cumulative normalised character position. Immune to drift from
  inter-scene TTS pauses.
- **Strategy B (time fallback):** when the text cannot be reconstructed, accumulate
  `scene_start_times` / `scene_durations`. The end is clamped to `audio_duration` so a length boost
  on the last sentence cannot push the final cue past the audio.

## 2. Which generator ran

`generate_subtitles_common` branches on segment count:

| Segments | With cues | Without cues |
|----------|-----------|--------------|
| > 1 | `generate_cue_aware_srt` (exact cue alignment) | `_generate_scene_aware_srt` — legacy heuristic, scales segment durations proportionally to audio length |
| 1 | `cues_to_srt` (word-level cues) | `text_to_srt` (durations estimated from plain text) |

Post-processing then applies `enforce_max_lines` (≤ 2 lines per cue, tuned for short Chinese
subtitles). With `subtitle_style_mode="llm"` an LLM also produces `subtitle_styles.json`.

## 3. The resume trap (fixed, but check it first)

**Symptom:** subtitles come out as the legacy heuristic — visibly less well aligned than the same
configuration produced on a fresh run.

**Root cause (historical):** on resume the audio file already exists, so `_step_audio` was skipped
and returned `None`; `sub_maker` was lost and the subtitle step fell back to the heuristic path.

**Fix:** `BasePipeline._recover_sub_maker()` re-harvests cues only (without regenerating audio bytes)
whenever the audio step is skipped and cues are needed. Wired into creative, manuscript, anchor,
multi-scene and poetry (per scene).

Still check it, because it tells you which path produced the file:

1. Did the run resume, or did it run end to end? (`task_state.json`, checkpoint history)
2. Is the subtitle file legacy-shaped — scene boundaries falling on proportional durations rather
   than on word boundaries?
3. Poetry is per scene: `scene_{i}/subtitle.srt`, each with its own cues. A missing cue set affects
   only that scene.

## 4. Narration text quality

`clean_narration_text()` strips Markdown structure (`#` headings, `**bold**`, `-` lists) and metadata
lines (story title, target audience, etc.) that the LLM may echo, then merges the result into a
single plain paragraph before TTS. Creative and poetry narrations are cleaned; a resumed run cleans a
reused narration again, which repairs older dirty data.

**Symptom of a regression here:** the narration literally reads headings or "target audience" aloud,
and that text is burned into the subtitles. Check `prompts.json → narrations[0]`; if it is a
structured document, the cleaning step was bypassed.

## 5. Poetry and Arabic specifics

- Poetry: narration text is the **original poem line** per scene, and each scene has its own cue
  alignment. Users may override the LLM's per-scene prompts.
- Arabic (`audio_add_tashkeel`): diacritics are added to the text **sent to TTS only**. Subtitles and
  `narration.txt` intentionally remain free of them. A "subtitles are missing the diacritics" report
  is expected behaviour, not a bug.
- Manuscript narration is the user's own text, so none of the LLM cleaning concerns apply there.

## 6. Checklist for "subtitles are wrong"

```bash
python3 scripts/diagnose_task.py <task_id>          # step states + which artifacts exist
ffprobe -v error -show_entries format=duration -of csv=p=0 <task_dir>/combined_narration.mp3
cat <task_dir>/combined_narration.txt               # is the text clean?
head -40 <task_dir>/combined_narration.srt          # cue boundaries: word-level or block-level?
```

Then answer, in order: was there a resume? Does the audio duration match the subtitle end? Is the
narration text the one that was actually synthesised? Only then look at the code.

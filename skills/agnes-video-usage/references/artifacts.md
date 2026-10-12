# Artifacts: layout, manifest and write-back

> Source anchor: upstream `docs/dev/artifact_standard.md`, `docs/dev/pipeline_products.md`.
> Last verified: 2026-10-12.

Artifacts are designed to be **transparent, readable, editable and replaceable** by external tools.
Filenames and directory names are fixed — never randomised.

## 1. Task directory

```
workspaces/<ws>/<YYYYmmdd_HHMMSS>_<task_id>/
├── task_state.json          # task state (polled by the service)
├── manifest.json            # artifact manifest (auto-generated)
├── MANIFEST.md              # human-readable directory guide (auto-generated)
├── story.txt                # creative
├── script.json              # creative storyboard
├── prompts.json             # prompts recorded per step
├── character_reference.png  # character reference
├── combined_narration.mp3   # narration audio (creative)
├── combined_narration.txt   # narration plain text (exported)
├── full_narration.mp3       # narration audio (manuscript / anchor)
├── full_narration.txt       # script plain text (exported)
├── full_subtitle.srt        # subtitles (manuscript / anchor)
├── narration.txt            # full recitation text (poetry)
├── scene_{i}/               # per scene (creative / poetry)
│   ├── video.mp4
│   ├── task.json            # video_id cache
│   ├── curl.sh              # ready-made query command
│   └── end_frame.png
└── final_video.mp4
```

The absolute path is `manifest.json → working_dir`, also shown in `MANIFEST.md` and in the Web UI.

## 2. Formats

| Kind | Format |
|------|--------|
| Text | UTF-8, no BOM |
| JSON | UTF-8, `indent=2`, `ensure_ascii=False` |
| Subtitles | standard SubRip, UTF-8, contiguous sequence numbers |
| Images | PNG (jpg/png/webp accepted when uploading a replacement) |
| Video | MP4, H.264 + AAC |
| Audio | MP3 |

## 3. `manifest.json`

Written when a run starts and ends; for old or queued tasks it can be built on demand.

```json
{
  "format_version": "1.0",
  "task_id": "abc123",
  "task_type": "creative",
  "task_status": "running",
  "dir_name": "20261012_101500_abc123",
  "working_dir": "/workspaces/ws1/20261012_101500_abc123",
  "artifacts": [
    {
      "artifact_id": "creative:script",
      "category": "json",
      "scope": "task",
      "path": "script.json",
      "exists": true,
      "editable": true,
      "schema_hint": "storyboard JSON array; scenes[].scene_prompt = visual description …",
      "generated_by_step": "script",
      "preview_url": "/api/tasks/abc123/artifacts/creative:script/file"
    }
  ],
  "files": [{ "path": "scene_0/video.mp4", "size": 1024000 }]
}
```

| Field | Meaning |
|-------|---------|
| `artifacts` | structured artifacts — defined for **creative / manuscript / anchor**; empty for `simple` and `poetry`, which fall back to `files` |
| `files` | the task directory's complete file tree (relative path + size), present for every type |
| `schema_hint` | human-readable field description, for external agents and tools |
| `editable` | text/JSON/SRT are editable; image/video/audio can be replaced |
| `preview_url` | preview/download endpoint |

## 4. Exported narration text

Every pipeline with narration writes a plain-text twin next to the audio:

| Pipeline | Audio | Exported text |
|----------|-------|---------------|
| creative | `combined_narration.mp3` | `combined_narration.txt` |
| manuscript / anchor | `full_narration.mp3` | `full_narration.txt` |
| poetry | per-scene `scene_{i}/narration.mp3` | `narration.txt` (whole poem) |

This is the file to edit when the request is "polish the narration" — the service re-runs audio and
subtitles from it.

## 5. Endpoints

| Endpoint | Purpose |
|----------|---------|
| `GET /api/tasks/{id}/artifacts` | artifact list, including `file_relpath`, `schema_hint`, `preview_url`, `dir_name` |
| `GET /api/tasks/{id}/manifest` | `manifest.json` |
| `GET /api/tasks/{id}/manifest.md` | `MANIFEST.md` |
| `GET /api/tasks/{id}/artifacts/{artifact_id}/file` | preview / download one artifact |
| `GET /api/tasks/{id}/artifacts/{artifact_id}/cascade-preview` | preview what deleting it would take with it |
| `DELETE /api/tasks/{id}/artifacts/{artifact_id}` | delete it, cascading |
| `POST /api/tasks/{id}/artifacts/{artifact_id}/upload` | replace it |

## 6. Collaboration rules for external tools

1. Text / JSON / SRT: edit the same file, or use the editor; the write-back triggers a downstream
   re-run.
2. Image / video / audio: process with ffmpeg or Python and **overwrite the same filename**, or
   upload a replacement.
3. JSON: change only the specified fields, keep UTF-8 and `indent=2`.
4. Affected downstream steps re-run according to the artifact cascading rules.
5. Never rename an artifact — the dependency graph matches by name.

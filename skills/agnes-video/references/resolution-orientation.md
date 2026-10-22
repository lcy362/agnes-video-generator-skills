# Resolution and orientation

> Source anchor: upstream `docs/dev/agnes_video_upstream_behavior.md` §5,
> `docs/dev/pipeline_products.md` §1.6–1.7. Last verified: 2026-10-12.

Two hard constraints govern every "the size is wrong" or "the video is sideways" report:

1. **Never validate artifacts via `perf_params`.** It is the internal inference size, not the
   container size (a v2.0 request for 768×1152 reports `perf_params` 832×1088). Measure the produced
   file with `ffprobe`.
2. **A width/height ratio check cannot detect a rotated image.** The container can be a correct
   portrait size while the pixels are laid out for landscape. Every existing ratio-based check
   passes this defect.

## 1. v2.0 — standard tiers are honoured, non-standard ones snap

| Requested W×H | Produced container (ffprobe) | `perf_params` | Verdict |
|---------------|------------------------------|---------------|---------|
| 768×1152 (this project's portrait tier) | **768×1152** | 832×1088 | honoured |
| 1280×720 (this project's landscape tier) | **1280×720** | 1280×704 | honoured |
| 1152×768 (the demo's "16:9", actually 3:2) | 1088×832 | 1088×832 | snapped to ≈4:3 (1.50 → 1.31) |
| 768×1360 (the demo's "9:16") | 704×1280 | 704×1280 | snapped, but lands exactly on 9:16 |

Rule: when the request hits a common standard pixel tier the container equals the request; otherwise
upstream re-draws onto its own latent bucket.

## 2. 2.5 series — the ratio is honoured, the absolute pixel count is not

`size` is fixed at `720P` and `aspect_ratio` is an enum. The UI labels like `720×1280` or `720×960`
are **ratio hints only**:

| `aspect_ratio` | Produced container | Orientation |
|----------------|--------------------|-------------|
| `16:9` | 1280×720 | correct |
| `9:16` | 720×1280 | **content rotated 90° clockwise** (see §3) |
| `3:4` | 834×1112 (ratio 0.75 honoured) | correct |
| `1:1` | not measured | — |

So regression checks for this series can only assert the **ratio**.

## 3. The 9:16 portrait defect

Upstream swaps the container dimensions for 9:16 but **does not rotate the pixels**; the artifact
contains no `display matrix` / rotation metadata (confirmed with ffprobe). The result is a portrait
container holding a landscape composition lying on its side, and it propagates through stitching and
subtitle overlay into the final video. Because the service sends the same payload as the official
demo, self-hosted users hit it too.

**Default behaviour:** the UI shows a hint when 9:16 is selected on a 2.5-series model and does
**not** alter the picture.

**Optional correction:** set `AGNES_FIX_V25_PORTRAIT_ROTATION=1` to enable detection-based
correction. It fires only when the signature matches — internal inference dimensions landscape
(`perf_params.width > perf_params.height`) while the produced container is portrait — and then runs
`ffmpeg -vf transpose=2` (90° counter-clockwise), logging under `[UpstreamRotate]`. The correction
happens in `VideoOutput.save()`, after download and before scene registration and scaling, so every
downstream stage already sees upright material. Any failure keeps the original file and does not
break the run.

## 4. How to check a file

```bash
python3 scripts/check_media.py out.mp4          # container, rotation metadata, audio, defect signature
ffprobe -hide_banner out.mp4                    # raw streams; look for Display Matrix
```

To localise a defect, check a single `scene_{i}/video.mp4` first: if one scene is sideways, the
problem is upstream, not the compositor.

## 5. Reporting

When reporting this class of problem, always include:

- the requested `aspect_ratio` / `width`×`height`, the model, and `seconds`
- `ffprobe` output for the scene file **and** the final video
- whether `AGNES_FIX_V25_PORTRAIT_ROTATION` was set

Do **not** report `perf_params` as evidence of the produced size.

#!/usr/bin/env python3
"""Inspect a produced media file: container size, ratio, duration, audio, rotation metadata.

This is the only legitimate way to verify resolution and orientation - never trust
perf_params, and never trust the requested pixel size.

Usage:
  check_media.py FILE [FILE ...]
  check_media.py FILE --expect-size 768x1152
  check_media.py FILE --expect-ratio 9:16
  check_media.py FILE --perf-size 832x1088     # evaluate the known 9:16 defect signature
  check_media.py FILE --json

--perf-size takes the upstream perf_params values (internal inference size). Combined with a
portrait container and no rotation metadata, that reproduces the service's own defect signature:
upstream swapped the container dimensions for 9:16 without rotating the pixels.

Requires ffprobe, or falls back to parsing ffmpeg output.
Exit codes: 0 all checks passed, 1 a check failed or the file cannot be read.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys


def die(message: str, code: int = 1) -> "None":
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(code)


def which(*names: str) -> "str | None":
    for name in names:
        path = shutil.which(name)
        if path:
            return path
    return None


def probe_json(ffprobe: str, path: str) -> dict:
    cmd = [ffprobe, "-v", "error", "-print_format", "json", "-show_streams", "-show_format", path]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        die(f"ffprobe failed on {path}: {result.stderr.strip()[:300]}")
    try:
        return json.loads(result.stdout)
    except ValueError:
        die(f"ffprobe returned unparsable output for {path}")


def probe_fallback(ffmpeg: str, path: str) -> dict:
    """Parse `ffmpeg -i` stderr - used when ffprobe is unavailable (e.g. imageio-ffmpeg only)."""
    result = subprocess.run([ffmpeg, "-hide_banner", "-i", path], capture_output=True, text=True)
    text = result.stderr
    info: dict = {"_source": "ffmpeg-stderr-fallback", "streams": []}
    duration = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", text)
    if duration:
        hours, minutes, seconds = duration.groups()
        info["duration"] = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("Stream #") and "Video:" in line:
            size = re.search(r"(\d{2,5})x(\d{2,5})", line)
            if size:
                info["streams"].append({"codec_type": "video", "width": int(size.group(1)), "height": int(size.group(2))})
        elif line.startswith("Stream #") and "Audio:" in line:
            info["streams"].append({"codec_type": "audio"})
    return info


def ratio_value(spec: str) -> float:
    try:
        width, height = spec.replace("×", "x").split("x")
        return float(width) / float(height)
    except (ValueError, ZeroDivisionError):
        die(f"expected WxH, got {spec!r}")


def rotation_of(stream: dict) -> "float | None":
    for side in stream.get("side_data_list") or []:
        if "rotation" in side:
            try:
                return abs(float(side["rotation"]))
            except (TypeError, ValueError):
                continue
    tag = (stream.get("tags") or {}).get("rotate")
    if tag is not None:
        try:
            return abs(float(tag))
        except (TypeError, ValueError):
            return None
    return None


def inspect(path: str, args: argparse.Namespace) -> tuple:
    """Return (report dict, list of (ok, message) checks)."""
    ffprobe = which("ffprobe")
    ffmpeg = which("ffmpeg")
    if ffprobe:
        data = probe_json(ffprobe, path)
        source = "ffprobe"
    elif ffmpeg:
        data = probe_fallback(ffmpeg, path)
        source = "ffmpeg stderr (no ffprobe on PATH)"
    else:
        die(
            f"neither ffprobe nor ffmpeg is available - cannot inspect {path}\n"
            "Install ffmpeg (brew install ffmpeg / apt install ffmpeg) or use the bundled imageio-ffmpeg."
        )

    streams = data.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = [s for s in streams if s.get("codec_type") == "audio"]
    if video is None and "streams" in data:
        die(f"{path}: no video stream found")
    if video is None:
        die(f"{path}: could not determine the video stream with the ffmpeg fallback")

    width = video.get("width")
    height = video.get("height")
    rotation = rotation_of(video)
    duration = data.get("duration")
    if duration is None:
        duration = (data.get("format") or {}).get("duration")
    try:
        duration = float(duration) if duration is not None else None
    except (TypeError, ValueError):
        duration = None

    report = {
        "file": path,
        "probe_source": source,
        "width": width,
        "height": height,
        "ratio": round(width / height, 4) if width and height else None,
        "duration_s": round(duration, 3) if duration else None,
        "video_codec": video.get("codec_name"),
        "audio_streams": len(audio),
        "audio_codec": audio[0].get("codec_name") if audio else None,
        "rotation_metadata_deg": rotation,
    }

    checks = []
    if width and height:
        checks.append((True, f"container {width}x{height} (ratio {width / height:.3f})"))
    else:
        checks.append((False, "container dimensions unknown"))
    checks.append((duration is not None, f"duration {duration if duration is None else round(duration, 3)}s"))
    checks.append((bool(audio), f"audio streams: {len(audio)}" + (f" ({report['audio_codec']})" if audio else "")))
    checks.append(
        (rotation is None, "no rotation metadata" if rotation is None else f"rotation metadata {rotation} deg")
    )

    if args.expect_size and width and height:
        want_w, want_h = (float(part) for part in args.expect_size.replace("×", "x").split("x"))
        within = abs(width - want_w) / want_w <= 0.15 and abs(height - want_h) / want_h <= 0.15
        checks.append((within, f"expected {args.expect_size} +/-15% (container is {width}x{height})"))

    if args.expect_ratio and width and height:
        want = ratio_value(args.expect_ratio)
        got = width / height
        within = abs(got - want) / want <= 0.15
        checks.append((within, f"expected ratio {args.expect_ratio} ({want:.3f}) +/-15% (container ratio {got:.3f})"))

    # The 9:16 defect signature: internal inference size landscape, container portrait, no rotation.
    if args.perf_size and width and height:
        perf_w, perf_h = (float(part) for part in args.perf_size.replace("×", "x").split("x"))
        signature = perf_w > perf_h and height > width and rotation in (None, 0)
        checks.append((
            not signature,
            "portrait-defect signature PRESENT: perf_params landscape, container portrait, no rotation metadata "
            "-> the picture is very likely rotated 90 deg; correct with `ffmpeg -vf transpose=2` "
            "or set AGNES_FIX_V25_PORTRAIT_ROTATION=1" if signature
            else "portrait-defect signature absent",
        ))
    elif args.perf_size:
        checks.append((False, "--perf-size given but container dimensions are unknown"))

    if not args.perf_size and width and height and height > width:
        checks.append((
            True,
            "container is portrait - a rotation defect cannot be proven from the file alone; "
            "pass --perf-size to evaluate the known signature, or compare the composition visually",
        ))

    return report, checks


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="check_media.py",
        description="Inspect a produced media file (container, ratio, duration, audio, rotation).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("files", nargs="+")
    parser.add_argument("--expect-size", metavar="WxH", help="assert the container size with +/-15%% tolerance")
    parser.add_argument("--expect-ratio", metavar="W:H", help="assert the aspect ratio with +/-15%% tolerance")
    parser.add_argument("--perf-size", metavar="WxH",
                        help="upstream perf_params (internal inference size); enables the portrait-defect check")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    reports = []
    failed = False
    for path in args.files:
        report, checks = inspect(path, args)
        report["checks"] = [{"ok": ok, "message": message} for ok, message in checks]
        reports.append(report)
        if not args.json:
            print(f"\n{path}")
            print("-" * len(path))
            for ok, message in checks:
                print(f"  {'PASS' if ok else 'FAIL'}  {message}")
        if any(not ok for ok, _ in checks):
            failed = True

    if args.json:
        print(json.dumps(reports, ensure_ascii=False, indent=2))

    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

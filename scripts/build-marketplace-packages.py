#!/usr/bin/env python3
"""Build per-marketplace release packages for skills/agnes-video.

Two domestic storefronts read the same skill but disagree on frontmatter:

  SkillHub (skillhub.cn)        camelCase keys, 宽松结构
  WorkBuddy open platform       snake_case keys + .codebuddy-plugin/plugin.json,
                                at most two directory levels inside the zip

The canonical source stays skills/agnes-video/SKILL.md (lowercase, generic
frontmatter). This script never edits it; it rewrites the frontmatter into a
throwaway copy and zips that copy under dist/marketplace/.

Usage:
    python3 scripts/build-marketplace-packages.py            # both packages
    python3 scripts/build-marketplace-packages.py --only workbuddy
"""

from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import sys
import tempfile
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
SKILL_DIR = ROOT / "skills" / "agnes-video"
DIST = ROOT / "dist" / "marketplace"
VERSION = "1.0.0"
AUTHOR = "lcy362 (SandGrid)"

# Keep every value on one line and never use ": " (colon + space): YAML reads
# that as a nested mapping and both storefronts reject the package.
DESCRIPTION_EN = (
    "Generate AI video for free with Agnes Video — text-to-video, image-to-video, "
    "keyframes, digital-human presenter, poem recitation, manuscript-to-video and still "
    "images, with AI narration and subtitles. Completely free and open source (MIT) — no "
    "subscription, no credits, no per-second billing, no GPU. It runs locally and calls "
    "Agnes AI's free models, so the only requirement is one free API key."
)

DESCRIPTION_ZH = (
    "免费生成 AI 视频 —— 文生视频、图生视频、关键帧动画、数字人口播、诗词朗诵、文章成片与"
    "静态图片，自带 AI 旁白与字幕。完全免费且开源（MIT），无订阅、无积分、无按秒计费、"
    "不需要显卡：服务跑在本地，生成走 Agnes AI 的免费模型，唯一要求是一个免费 API Key。"
)

DISPLAY_NAME = "Agnes Video — Free AI Video Generation"
DISPLAY_NAME_EN = "Agnes Video — Free AI Video Generation"
DISPLAY_NAME_ZH = "Agnes Video —— 免费 AI 视频生成"

SKILLHUB_FRONTMATTER = f"""---
name: agnes-video
displayName: {DISPLAY_NAME}
description: {DESCRIPTION_EN}
version: {VERSION}
category: 效率工具
platforms: Claude Code, Cursor, Codex, TRAE, WorkBuddy, CodeBuddy
author: {AUTHOR}
license: MIT
---
"""

WORKBUDDY_FRONTMATTER = f"""---
name: agnes-video
display_name: {DISPLAY_NAME}
display_name_en: {DISPLAY_NAME_EN}
description: {DESCRIPTION_EN}
description_zh: {DESCRIPTION_ZH}
description_en: {DESCRIPTION_EN}
version: {VERSION}
category: productivity
author: {AUTHOR}
license: MIT
---
"""

PLUGIN_JSON = {
    "name": "agnes-video",
    "display_name": DISPLAY_NAME,
    "display_name_en": DISPLAY_NAME_EN,
    "display_name_zh": DISPLAY_NAME_ZH,
    "version": VERSION,
    "description": DESCRIPTION_EN,
    "description_zh": DESCRIPTION_ZH,
    "description_en": DESCRIPTION_EN,
    "author": AUTHOR,
    "license": "MIT",
    "homepage": "https://github.com/lcy362/agnes-video-generator-skills",
    "repository": "https://github.com/lcy362/agnes-video-generator-skills",
    "keywords": ["free ai video", "text to video", "ai video generator"],
}


def split_skill_md() -> str:
    """Return SKILL.md body with the original frontmatter stripped."""
    text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    if not text.startswith("---"):
        raise SystemExit("SKILL.md has no frontmatter")
    end = text.find("\n---", 3)
    if end == -1:
        raise SystemExit("SKILL.md frontmatter is not closed")
    return text[end + len("\n---"):].lstrip("\n")


def stage(target: pathlib.Path, frontmatter: str) -> pathlib.Path:
    """Copy the skill into a temp staging root as <root>/agnes-video/."""
    root = pathlib.Path(tempfile.mkdtemp(prefix="agnes-pkg-"))
    dest = root / "agnes-video"
    shutil.copytree(
        SKILL_DIR,
        dest,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"),
    )
    (dest / "SKILL.md").write_text(frontmatter + "\n" + split_skill_md(), encoding="utf-8")
    return root


def zip_dir(root: pathlib.Path, out: pathlib.Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(root.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(root).as_posix())


def build(site: str) -> pathlib.Path:
    if site == "skillhub":
        root = stage(DIST, SKILLHUB_FRONTMATTER)
        out = DIST / f"agnes-video-skillhub-{VERSION}.zip"
    elif site == "workbuddy":
        root = stage(DIST, WORKBUDDY_FRONTMATTER)
        plugin_dir = root / "agnes-video" / ".codebuddy-plugin"
        plugin_dir.mkdir(exist_ok=True)
        (plugin_dir / "plugin.json").write_text(
            json.dumps(PLUGIN_JSON, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        out = DIST / f"agnes-video-workbuddy-{VERSION}.zip"
    else:
        raise SystemExit(f"unknown site: {site}")

    zip_dir(root, out)
    shutil.rmtree(root, ignore_errors=True)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--only", choices=["skillhub", "workbuddy"], help="build a single package"
    )
    args = parser.parse_args()

    if not SKILL_DIR.is_dir():
        print(f"skill directory not found: {SKILL_DIR}", file=sys.stderr)
        return 1

    sites = [args.only] if args.only else ["skillhub", "workbuddy"]
    for site in sites:
        out = build(site)
        print(f"{site:10s} -> {out}  ({out.stat().st_size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

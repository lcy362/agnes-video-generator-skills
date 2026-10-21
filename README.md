# agnes-video-generator-skills

Companion skills for [agnes-video-generator](https://github.com/lcy362/agnes-video-generator).

Install them once and your coding agent can drive the whole thing: it installs the service on demand,
generates videos, explains failures, and changes the project's code — no clone of the upstream
repository, no commands typed by you.

## Quick start

The skills are plain directories plus small scripts: no service code, and no credentials ever pass
through them.

```bash
git clone https://github.com/lcy362/agnes-video-generator-skills.git
npx flint-skills-hub     # Sources → add the cloned directory (flint reads its skills/ subdirectory)
```

[**flint**](https://github.com/lcy362/flint) is a local-first, open-source skills manager. It deploys
the skills into any agent directory (Claude Code, Cursor, Codex, TRAE and more) by symlink or copy —
no cloud, no account, no telemetry. It reads **local** sources only and never clones anything for
you, so you register the directory you just cloned. Flatten into the local library instead? Copy each
`skills/<name>/` into `~/local-skills/skills/<name>/` — note this repository is **nested**
(`skills/<name>/`) while a flint-managed library is **flat**.

**No flint?** Copy them in by hand. The trade-off is that you repeat it for every project and every
new agent:

```bash
cp -R agnes-video-generator-skills/skills/* <project>/.agents/skills/
```

### The skills install the service themselves

The upstream repository does **not** need to be cloned. `agnes-video-usage` runs
`scripts/bootstrap.py install`, which puts the service under `~/.agnes-video` (override with
`AGNES_HOME`), keeps its own venv there, skips `pip` when `requirements.txt` is unchanged, starts the
service on `localhost:8765` and verifies it through the real endpoints. Config, workspace and
finished videos live in that same data root; nothing is written into your project.

## What you can ask for

> "Make a creative long video about the Voyager probes, with narration and subtitles."

> "My task `4de1bcd26fda` failed — find out why and tell me if it is worth fixing."

> "The portrait video came out sideways. Diagnose it and fix the configuration."

> "Take my finished task, improve the storyboard prompts, and regenerate only the affected scenes."

| Skill | Use it when you want to |
|-------|-------------------------|
| `agnes-video-usage` | Install and start the service, pick among the six task types, create tasks and poll progress, **Manual Mode checkpoints + have the agent rewrite artifacts** before resuming |
| `agnes-video-troubleshoot` | Attribute a failure: queue-full and `401`, timeouts, wrong resolution, upside-down portrait output, broken subtitle timeline, evidence collection |
| `agnes-video-contrib` | Change the project's code: branch and English-commit rules, pre-flight, frontend rebuild into `static/`, i18n, large-version regression |

Each `SKILL.md` carries the trigger phrases an agent matches against. Keep them in sync with how the
project actually talks about its features — that is the part of this repository that has to stay
accurate.

**Direct-API skills are a different thing.** `agnes-video-gen`, `agnes-image-gen` and
`agnes-ai-generation` talk straight to `apihub.agnes-ai.com` and bypass the service. Use those for a
quick one-off video; use this repository when you need the six pipelines, narration, subtitles or
Manual Mode artifact editing.

**Out of scope: releasing.** A release involves a human review gate and stays with the maintainer
(upstream `docs/dev/release_process.md`). Encoding it as a skill would only invite misuse.

## Layout

```
agnes-video-generator-skills/
├─ README.md            # this file (for humans)
├─ AGENTS.md            # for agents editing this repository: conventions + sync rules
└─ skills/
   ├─ agnes-video-usage/
   │   ├─ SKILL.md
   │   ├─ references/   # bootstrap-contract / deploy / task-types / manual-mode / artifacts
   │   └─ scripts/      # bootstrap.py, agnes_task.py, verify_deploy.sh
   ├─ agnes-video-troubleshoot/
   │   ├─ SKILL.md
   │   ├─ references/   # upstream-errors / resolution-orientation / subtitle-timeline / task-forensics
   │   └─ scripts/      # diagnose_task.py, check_media.py, report_issue.py
   └─ agnes-video-contrib/
       ├─ SKILL.md
       ├─ references/   # workflow / dev-standards / testing / frontend-i18n / regression
       └─ scripts/      # preflight.sh
```

## Requirements

- Target service defaults to `http://localhost:8765` (override with `AGNES_VIDEO_BASE`)
- Scripts use the Python 3.10+ standard library plus `curl` and `ffprobe`
- Scripts **ignore HTTP proxies on purpose**: on macOS `urllib` reads the system proxy settings but
  not their exception list, so a configured proxy turns every local API call into a `502` from the
  proxy. `curl` is unaffected by this.
- No network calls for validation, no telemetry, and **no credentials are ever committed**

## Source of truth

Every claim in these skills comes from upstream's measured documentation. Those documents
remain authoritative:

| Topic | Upstream authoritative document |
|-------|--------------------------------|
| Agent operation, bootstrap contract | `docs/public/agent-operations.md` |
| Artifact logic, subtitle cue timeline | `docs/dev/pipeline_products.md` |
| Measured upstream API behavior, resolution and orientation | `docs/dev/agnes_video_upstream_behavior.md` |
| Artifact standard and external-tool collaboration | `docs/dev/artifact_standard.md` |
| Manual Mode | `docs/public/manual_mode_guide.md` |
| Regression scenario matrix | `docs/dev/regression_test_plan.md` |
| Endpoint inventory | `docs/public/api.md` |
| Development rules and hard constraints | upstream `AGENTS.md` |

When upstream documentation changes, re-verify the matching `references/` file here
(see `AGENTS.md` §4).

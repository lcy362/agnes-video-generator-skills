# agnes-video-generator-skills

Companion skills for [agnes-video-generator](https://github.com/lcy362/agnes-video-generator).
No service code here — this repository turns "how to use it, how to debug it, how to change it"
into operational skills an AI agent can execute directly.

## Why this exists

The upstream project documents itself in `AGENTS.md` and `docs/dev/*.md`, but those are long
documents written **for an agent working inside that repository**. Everyday work happens
somewhere else:

- **Using** the service (start it, create a task, watch progress, verify artifacts, recover)
- **Debugging** a failed run from another directory, in a different agent session
- **Contributing** a fix from a fork

In all three cases the agent cannot (and should not) read dozens of upstream docs.

So this repository does one thing: **it indexes and operationalizes, it does not duplicate.**
Each skill is a decision tree plus pointers plus runnable scripts. When detail is needed,
the pointer leads back to the authoritative upstream document.

## The three skills

| Skill | For | Covers | Trigger phrases |
|-------|-----|--------|-----------------|
| `agnes-video-usage` | **Users** | Deploy and start, pick among the six task types, create tasks and poll progress, **Manual Mode checkpoints + have a local agent rewrite artifacts**, artifact write-back and cascade re-run | "generate a video with agnes", "run a creative long video", "edit the storyboard at the checkpoint" |
| `agnes-video-troubleshoot` | **Users / maintainers** | Task failure attribution, queue-full and 401, timeouts, wrong resolution, upside-down portrait output, broken subtitle timeline, evidence collection | "the task keeps failing", "503 / 401", "the video is sideways", "subtitles are out of sync" |
| `agnes-video-contrib` | **Contributors** | Branch and English-commit rules, local pre-flight, frontend changes must rebuild and commit `static/`, i18n must update zh+en, large-version regression | "open a PR for agnes-video-generator", "change its frontend", "run the regression" |

### Not overlapping the existing `agnes-*` skills

`agnes-video-gen`, `agnes-image-gen` and `agnes-ai-generation` talk **directly to the upstream API**
(`apihub.agnes-ai.com`) and bypass the service entirely. This repository drives **the service itself**.
They coexist:

- Just want a quick video without running a server → `agnes-video-gen`
- Need the six pipelines (creative / manuscript / anchor / poetry), subtitles and voices,
  or Manual Mode artifact editing → `agnes-video-usage`
- The service will not start or a task will not finish → `agnes-video-troubleshoot`

### Explicitly out of scope

**Releasing is not here.** Release involves a human review gate and is performed by the
maintainer personally (see upstream `docs/dev/release_process.md`). Encoding it as a skill
would only invite misuse.

## How it relates to agnes-video-generator

The project describes agent-driven operation in three levels, and this repository **is level 2**:

| Level | What it is | Where it lives |
|-------|-----------|----------------|
| 1 | Point your agent at the project — it reads `AGENTS.md` | [`docs/public/agent-operations.md`](https://github.com/lcy362/agnes-video-generator/blob/master/docs/public/agent-operations.md) |
| **2** | **Install this skill set — the agent stops having to learn the project first** | **this repository** |
| 3 | Distribute the skills to every agent you use | [flint](https://github.com/lcy362/flint) |

Two consequences worth knowing:

- The **authoritative description** of levels 1–3 is the project document linked above. When it and this repository disagree, that document wins.
- The **`description` field of each `SKILL.md`** is what an agent matches against to pick a skill up. Keep those trigger phrases in sync with how the project actually talks about its features — that is the part of this repository that has to stay accurate.

When the upstream project changes behaviour that a skill documents, update the skill in the same round; the per-file source anchors in each `references/*.md` say which upstream document it was verified against.

## Layout

```
agnes-video-generator-skills/
├─ README.md            # this file (for humans)
├─ AGENTS.md            # for agents editing this repository: conventions + sync rules
└─ skills/
   ├─ agnes-video-usage/
   │   ├─ SKILL.md
   │   ├─ references/   # deploy / task-types / manual-mode / artifacts
   │   └─ scripts/      # agnes_task.py, verify_deploy.sh
   ├─ agnes-video-troubleshoot/
   │   ├─ SKILL.md
   │   ├─ references/   # upstream-errors / resolution-orientation / subtitle-timeline / task-forensics
   │   └─ scripts/      # diagnose_task.py, check_media.py
   └─ agnes-video-contrib/
       ├─ SKILL.md
       ├─ references/   # workflow / dev-standards / testing / frontend-i18n / regression
       └─ scripts/      # preflight.sh
```

## Installation

**Option 1 — flint as an external source (recommended)**

Register this repository in flint as an external source and pick the `nested` layout
(`auto` also works: a `skills/*/SKILL.md` subtree is detected as nested). Then distribute
individual skills to the agent directories you want.

**Option 2 — merge into the local skills library**

Copy each `skills/<name>/` directory into `~/local-skills/skills/<name>/` and let flint
distribute it. Note the layout difference: this repository is **nested** (`skills/<name>/`),
while a flint-managed `~/local-skills` is **flat**. Copy the skill directory itself — do not
copy the extra `skills/` level into it.

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
| Artifact logic, subtitle cue timeline | `docs/dev/pipeline_products.md` |
| Measured upstream API behavior, resolution and orientation | `docs/dev/agnes_video_upstream_behavior.md` |
| Artifact standard and external-tool collaboration | `docs/dev/artifact_standard.md` |
| Manual Mode | `docs/public/manual_mode_guide.md` |
| Regression scenario matrix | `docs/dev/regression_test_plan.md` |
| Endpoint inventory | `docs/public/api.md` |
| Development rules and hard constraints | upstream `AGENTS.md` |

When upstream documentation changes, re-verify the matching `references/` file here
(see `AGENTS.md` §4).

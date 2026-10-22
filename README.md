# agnes-video

**One skill that turns an idea into a finished video.** Describe the result you want and your coding
agent runs the task end to end: it installs the local service, generates the video, reports progress,
delivers the file, diagnoses failures, and — with your agreement — fixes a genuine defect and opens a PR.

The service installs on demand under `~/.agnes-video` (override with `AGNES_HOME`) and is reused
afterwards, so only the first run pays the setup cost.

## Quick start

```bash
git clone https://github.com/lcy362/agnes-video-generator-skills.git
npx flint-skills-hub     # Sources → add the cloned directory (flint reads its skills/ subdirectory)
```

[**flint**](https://github.com/lcy362/flint) is a local-first, open-source skills manager. It deploys
the skill into any agent directory (Claude Code, Cursor, Codex, TRAE and more) by symlink or copy —
no cloud, no account, no telemetry. It reads **local** sources only and never clones anything for
you, so you register the directory you just cloned. Prefer a flat library? Copy
`skills/agnes-video/` into `~/local-skills/skills/agnes-video/`.

**No flint?** Copy it in by hand — the trade-off is that you repeat this for every project and every
new agent:

```bash
cp -R agnes-video-generator-skills/skills/agnes-video <project>/.agents/skills/
```

## What it does

The skill is one closed loop, not a menu:

| Stage | You say | It does |
|-------|---------|---------|
| **Install** | "set up agnes video" | Probes, asks for consent, installs the service under `~/.agnes-video`, starts it on `localhost:8765`, proves readiness through the real endpoints |
| **Create** | "make a 60-second poetry video about the sea, with narration and subtitles" | Picks the pipeline (simple / creative / manuscript / anchor / poetry / image), asks for a free API key without it ever entering the chat, submits the task, reports deltas |
| **Deliver** | — | Copies the finished file to `$AGNES_HOME/outputs/<task_id>/` and reports the absolute path, duration and resolution |
| **Diagnose** | "the task keeps failing" / "the video is sideways" / "subtitles are out of sync" | Collects evidence (`diagnose_task.py`, `check_media.py`, diagnostics endpoint, `error_logs`), classifies it as configuration, upstream capacity, or a real defect |
| **Fix** | "yes, fix it" | For a small reproducible defect: forks, branches, fixes, runs the CI-equivalent pre-flight, and opens a PR |

Two things it deliberately does **not** do: release the project (maintainer-only, human review gate),
and change code before you have seen the root cause and agreed to the fix.

## The service it installs

`scripts/bootstrap.py` owns installation, so the skill stays useful even when the service is missing,
old, or running from Docker:

```bash
python3 scripts/bootstrap.py probe  --json    # read-only: what exists, what is missing
python3 scripts/bootstrap.py install --yes --json
python3 scripts/bootstrap.py verify --json    # readiness proof, costs no upstream quota
```

Everything lands in one data root — `~/.agnes-video` by default (`AGNES_HOME` overrides it): venv,
config (mode `0600`), workspace, outputs, task snapshots, logs. Nothing is written into your project,
pip runs only when `requirements.txt` actually changed, and a second run is a no-op.

## Layout

```
agnes-video-generator-skills/
├─ README.md            # this file (for humans)
├─ AGENTS.md            # conventions for editing this repository
└─ skills/agnes-video/
   ├─ SKILL.md          # the only entry point: the loop + minimal commands + pointers
   ├─ references/       # bootstrap-contract, deploy, pipeline-selection, task-types,
   │                    # manual-mode, artifacts, progress, upstream-errors,
   │                    # resolution-orientation, subtitle-timeline, task-forensics,
   │                    # upstream-probe, dev-standards, frontend-i18n, testing,
   │                    # regression, workflow
   └─ scripts/          # bootstrap.py, agnes_task.py, verify_deploy.sh, diagnose_task.py,
                        # check_media.py, report_issue.py, preflight.sh
```

## Requirements

- Target service defaults to `http://localhost:8765` (override with `AGNES_VIDEO_BASE`)
- Scripts use the Python 3.10+ standard library plus `curl` and `ffprobe`
- Scripts **ignore HTTP proxies on purpose**: on macOS `urllib` reads the system proxy settings but
  not their exception list, so a configured proxy turns every local API call into a `502` from the
  proxy. `curl` is unaffected by this.
- No telemetry, and **no credentials are ever committed**: the key goes in through the web UI, stdin,
  or the environment, never through argv

## Source of truth

The skill only indexes and operationalizes upstream's measured documentation; those documents remain
authoritative:

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

When upstream documentation changes, re-verify the matching `references/` file here (see `AGENTS.md` §4).

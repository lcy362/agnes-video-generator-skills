# AGENTS.md — conventions for working in this repository

> For AI agents adding or modifying skills in this repository.
> Goal: extend the skill set correctly **without turning this repo into a poor copy of the upstream docs**.

---

## 1. What this is

`agnes-video-generator-skills` ships **one standalone skill** that turns an idea into a finished
video: it installs [agnes-video-generator](https://github.com/lcy362/agnes-video-generator) on
demand, runs the task, diagnoses failures, and — once the user agrees — fixes a genuine service
defect and opens a PR. The skill is usable on its own; the project is its dependency, not its owner.
This repository contains **no service code** and does **not** copy upstream document bodies.

```
skills/agnes-video/
├─ SKILL.md          # the only entry point: install → create → deliver → diagnose → fix
├─ references/       # detail, one file per topic
└─ scripts/          # bootstrap, task control, diagnosis, pre-flight
```

## 2. Layout and naming

1. One skill, one directory: `skills/agnes-video/`, and **the directory name must equal `name` in
   `SKILL.md`**.
2. Skills live under `skills/` (nested layout). The repository root must **not** contain a
   `SKILL.md` — otherwise the whole repository is detected as a *single-skill repo* and collapses
   into one skill.
3. `SKILL.md` contains only: **when to use → the closed loop → minimal runnable commands →
   which reference/script to open next**. No long explanations; those belong in `references/`,
   which in turn point at upstream documents.
4. Documentation prose is English. Identifiers, filenames and commands are English too.
5. **Do not split the loop back into sibling skills.** Install, use, diagnose and fix share one
   bootstrap, one task model and one exit-code contract; separate skills drifted apart in practice.
   Add a reference file instead.

## 3. Frontmatter contract

```yaml
---
name: agnes-video               # must equal the directory name
description: ...                 # must state the scenario AND trigger phrases
agent_created: true
---
```

`description` is the single most important field in this repository: it is the only basis on
which an agent retrieves the skill. Include the phrasing users actually type
("the video is sideways", "the task keeps failing"), not just terminology.

## 4. Knowledge sync rules

> Upstream documents are **authoritative**. This repository only **indexes and operationalizes**.

1. **Never paste large blocks of upstream documentation.** Summarize long tables and long
   explanations in one line and link to the upstream path. Duplication guarantees drift.
2. Every `references/*.md` starts with a **source anchor**: upstream document path plus the date
   this skill was last verified against it.
3. When upstream documentation changes, re-verify the matching file here. If a conclusion no
   longer holds, **fix this repository, not upstream**. If upstream itself is wrong, raise an
   issue there — do not quietly publish a "corrected version" here.
4. Only **measured, settled** conclusions may be stated as hard rules here (e.g. "polling must use
   `video_id`", "2.5-flash portrait output is rotated"). Conclusions marked "not yet verified" or
   "single observation" must be written **together with their uncertainty**, never as a rule.

## 5. Script conventions

1. Python 3.10+ standard library only, plus `curl` and `ffprobe`. No new dependencies.
2. Read the service base URL from `AGNES_VIDEO_BASE`, defaulting to `http://localhost:8765`.
3. **Credentials never enter this repository.** Scripts read them from the environment or from
   the service's local config; documentation only ever names the variable.
4. Scripts must run standalone and print a usage block when misused. On failure, print the
   actionable next step — not a bare traceback.
5. Scripts that re-probe upstream emit **evidence** (HTTP status codes, body `status`/`error`,
   `ffprobe` output), not a success/failure verdict. Judgment stays with the reader.

## 6. Adding or changing a skill

```
Adding or changing something?
 ├─ Decide where it sits in the loop: install / use / diagnose / fix
 │   └─ Fits nowhere → raise it for discussion before writing
 │      (do NOT add a second skill; extend this one)
 ├─ Keep the directory: skills/agnes-video/
 ├─ Update SKILL.md only where the loop changes (frontmatter trigger phrases included)
 ├─ Scripts → scripts/ ; detail → references/ (with source anchor)
 └─ Self-check:
     ├─ frontmatter: name == directory name; description non-empty and contains trigger phrases
     ├─ python3 -m py_compile skills/*/scripts/*.py
     ├─ bash -n skills/*/scripts/*.sh
     └─ if runnable: actually execute it once against a live service or a --dry-run path
```

## 7. Boundaries (do not cross)

| Stage of the loop | Only does | Explicitly does not |
|-------------------|-----------|---------------------|
| Install / use | Bootstrap the service, pick a pipeline, drive the task, edit artifacts in Manual Mode | Hand-edit the service's code |
| Diagnose | Locate and collect evidence; state conclusions and next steps | Present a flaky observation as certainty; change code before the user agrees |
| Fix | Small, reproducible defects: change → pre-flight → PR | **Releasing**, maintainer-only operations, CI secret setup; speculative refactors |

**Releasing stays out of this repository.** It involves a human review gate and is performed by
the maintainer. `SKILL.md` may contain one sentence pointing at upstream
`docs/dev/release_process.md`, but must not spell out the steps.

## 8. Bootstrap conventions

`skills/agnes-video/scripts/bootstrap.py` is the single source of truth for installing and
starting the service. Rules for anything that touches it:

1. **Write only under `$AGNES_HOME`** (default `~/.agnes-video`). Never install, clone or create files
   in the user's current directory, and never write into a skill directory (it may be a read-only symlink).
2. **Exit codes are the interface.** `SKILL.md` and `references/bootstrap-contract.md` must list the same
   codes as the script; adding or changing one means updating all three in the same commit.
3. **npm is a distribution vehicle, not a launcher.** Do not call the package's `bin/cli.js` to run the
   service: it keeps its venv inside the npx cache and reinstalls Python dependencies on every start.
   Own the venv and skip pip via the requirements fingerprint.
4. **A repeat run must be a no-op.** Reuse a reachable service; reuse an install that satisfies
   `requires_service`; never silently upgrade.
5. **Credentials**: read a key only from stdin or the user's own web UI. Never from argv, never echoed,
   never written outside `config/`, never into a report or a task payload.
6. **Evidence over claims**: readiness is `verify` output, not "the process started".

---

## 9. After editing

- If the skill is already distributed to an agent directory, re-sync or re-distribute it through
  flint — never edit the deployed copy in place.
- Anything that is not part of a skill (task lists, scratch notes) stays outside `skills/`.

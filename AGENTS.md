# AGENTS.md — conventions for working in this repository

> For AI agents adding or modifying skills in this repository.
> Goal: extend the skill set correctly **without turning this repo into a poor copy of the upstream docs**.

---

## 1. What this is

`agnes-video-generator-skills` is the companion skill set for
[agnes-video-generator](https://github.com/lcy362/agnes-video-generator).
It turns three kinds of work — **using**, **debugging**, **contributing** — into skills an agent
can execute directly. This repository contains **no service code** and does **not** copy
upstream document bodies.

```
skills/<skill-name>/
├─ SKILL.md          # the only entry point: decision tree + minimal commands + pointers (required)
├─ references/       # detail (optional)
└─ scripts/          # executable scripts (optional)
```

## 2. Layout and naming

1. One skill per directory, `kebab-case`, and **the directory name must equal `name` in `SKILL.md`**.
2. Skills live under `skills/` (nested layout). The repository root must **not** contain a
   `SKILL.md` — otherwise the whole repository is detected as a *single-skill repo* and collapses
   into one skill.
3. `SKILL.md` contains only: **when to use → decision tree → minimal runnable commands →
   which reference/script to open next**. No long explanations; those belong in `references/`,
   which in turn point at upstream documents.
4. Documentation prose is English. Identifiers, filenames and commands are English too.

## 3. Frontmatter contract

```yaml
---
name: agnes-video-usage          # must equal the directory name
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
Adding a skill?
 ├─ Decide which skill it belongs to: usage / troubleshoot / contrib
 │   └─ Fits none of them → raise it for discussion first
 │      (avoid creating a fourth skill with fuzzy boundaries)
 ├─ Create the directory: skills/<kebab-name>/
 ├─ Write SKILL.md: frontmatter (name + description with trigger phrases) + decision tree + pointers
 ├─ Scripts → scripts/ ; detail → references/ (with source anchor)
 └─ Self-check:
     ├─ frontmatter: name == directory name; description non-empty and contains trigger phrases
     ├─ python3 -m py_compile skills/*/scripts/*.py
     ├─ bash -n skills/*/scripts/*.sh
     └─ if runnable: actually execute it once against a live service or a --dry-run path
```

## 7. Boundaries (do not cross)

| Skill | Only does | Explicitly does not |
|-------|-----------|---------------------|
| `agnes-video-usage` | Produce videos via the service; edit artifacts in Manual Mode | Modify service code |
| `agnes-video-troubleshoot` | Locate and collect evidence; state conclusions and next steps | Modify the upstream repository; present a flaky observation as a certainty |
| `agnes-video-contrib` | Change code → self-check → open a PR | **Releasing**, maintainer-only operations, CI secret setup |

**Releasing stays out of this repository.** It involves a human review gate and is performed by
the maintainer. The contrib skill may contain one sentence pointing at upstream
`docs/dev/release_process.md`, but must not spell out the steps.

## 8. After editing

- If the skill is already distributed to an agent directory, re-sync or re-distribute it through
  flint — never edit the deployed copy in place.
- Anything that is not part of a skill (task lists, scratch notes) stays outside `skills/`.

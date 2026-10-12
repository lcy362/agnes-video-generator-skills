---
name: agnes-video-contrib
description: Contribute code to the agnes-video-generator project and open a PR the way its CI and maintainer expect - branch and commit conventions (English commit messages are mandatory), local pre-flight checks (ruff, pytest with coverage gate, i18n completeness, mock regression), the rule that any frontend source change must be rebuilt into static/ and committed, and i18n text that must be added to both zh.json and en.json. Also covers running the 14-scenario large-version regression. Use when the user says "change agnes-video-generator", "fix a bug in it", "add a feature to it", "open a PR", "its CI failed", "static/ is out of date", "add a translation", or "run the regression". Not for releasing.
agent_created: true
---

# agnes-video-generator — contributing

Change the service's code and get the PR through CI. Repository:
`git@github.com:lcy362/agnes-video-generator.git` (a Gitee mirror is synced by CI; push to GitHub).

**Releasing is out of scope.** Version bumps and release notes involve a human review gate and are
performed by the maintainer — see upstream `docs/dev/release_process.md` for that flow, and do not
attempt it from this skill.

## 1. The two rules that fail most PRs

1. **Commit messages must be in English** — Conventional Commits prefix plus an English body.
   A Chinese commit message violates a stated hard rule and must be amended before pushing.
2. **Changed `frontend/src/` → run `npm run build` and commit the `static/` output.**
   `static/` is the shipped artifact for all three run modes, and CI has a dedicated job that
   rebuilds and then fails if `git status --porcelain static/` is non-empty. There is no hook
   protecting you.

## 2. Two entry paths

**Path A — a planned change** (user asks for a feature or a fix):

```bash
gh repo fork lcy362/agnes-video-generator --clone --remote   # origin = your fork, upstream = project
cd agnes-video-generator
git fetch upstream && git switch -c fix/short-description upstream/main

# … make the change, following references/dev-standards.md …

bash scripts/preflight.sh                                    # mirrors CI, stops at the first failure
git add -A && git commit -m "fix(video): <english summary>"  # English only
git push -u origin fix/short-description
gh pr create --repo lcy362/agnes-video-generator --fill
```

`preflight.sh --full` also runs the mock regression (slow); add `--frontend` when you touched
`frontend/`. Run it from the project root.

**Path B — a defect handed over by troubleshooting**: read
`references/workflow.md` §6 (hotfix path) before anything else. Diagnosis and fixing are separate
steps — **present the root cause and the proposed change, wait for the user to agree, then fix.**
One issue per PR, and verify with the exact path the dossier named.

## 3. Check → fix map

| CI job / check | Command | Fix |
|----------------|---------|-----|
| Lint | `ruff check core/ web/ utils/ models/ scripts/` | Fix findings; config in `ruff.toml` |
| i18n completeness | `python scripts/i18n_check.py` | Add missing keys — `zh` and `en` are both mandatory |
| Unit tests + coverage ≥ 55% | `pytest tests/ --cov=core --cov=models --cov=utils --cov=web --cov-fail-under=55` | Add or fix tests |
| Frontend unit tests | `cd frontend && npm test` | — |
| Type-check + build | `cd frontend && npm run build` | Fix type errors |
| **`static/` committed** | `git status --porcelain static/` must be empty | Rebuild and commit the output |
| Integration (no network) | `./scripts/run_mock_regression.sh` | See `references/testing.md` |

## 4. Which reference to open

| You are about to… | Read |
|-------------------|------|
| Make the actual change | `references/dev-standards.md` — architecture, log prefixes, response format, back-compat rules |
| Touch anything user-visible in the UI | `references/frontend-i18n.md` — i18n contract and the build/commit rule |
| Add or fix tests, run the mock suite | `references/testing.md` |
| Verify a large version before handing it over | `references/regression.md` — 14 scenarios, F/R/E acceptance |
| Open, update or answer a PR | `references/workflow.md` — branch, commit, PR body, review etiquette |

## 5. Rules that bite

- **Never commit a Chinese commit message** (see §1).
- **Never hand-edit `static/`** — it is generated; edit `frontend/src/` and rebuild.
- **Never renumber or drop i18n keys**; `zh` and `en` key sets must match 100%. Other languages
  may lag temporarily but are listed by the checker.
- **`core/pipeline.py`, `core/image_generator.py`, `core/video_generator.py`,
  `core/audio/subtitle.py`, `core/compositor/concatenator.py` are back-compat alias modules** —
  they re-export the real classes. Do not delete them.
- **Keep the two-track retry model intact** when touching upstream calls; all retry decisions must
  go through `core/api/retry_policy.py`.
- **During a regression run, do not change code** — record findings and fix only after confirmation.

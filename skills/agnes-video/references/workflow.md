# Fork, branch, commit and PR

> Source anchor: upstream `AGENTS.md` §九 (hard rules), `.github/workflows/`,
> `docs/dev/sonarcloud_analysis_workflow.md`. Last verified: 2026-10-12.

## 1. Remotes: fork first

Contributors do not push to the project repository. Work through a fork:

```bash
gh repo fork lcy362/agnes-video-generator --clone --remote
# --remote adds an "upstream" remote pointing at the project; origin is your fork

cd agnes-video-generator
git remote -v      # origin = your fork, upstream = lcy362/agnes-video-generator
```

Keep `upstream` as the only source you pull from, and `origin` as the only place you push to. A
Gitee mirror exists (`gitee https://gitee.com/sandgrid/agnes-video-generator.git`) — it is synced by
CI, never push to it.

```bash
git fetch upstream && git switch -c fix/thing upstream/$(git symbolic-ref --short refs/remotes/upstream/HEAD | sed 's|upstream/||')
```

## 2. Branches

```
fix/<short-description>        # bug fix
feat/<short-description>       # new behaviour
docs/<short-description>       # documentation only
refactor/<short-description>   # behaviour-preserving change
```

One topic per branch. Do not mix unrelated reformatting into a fix: the diff is the review, and noise
hides intent.

## 3. Commits

**English is mandatory** — title and body. This is a stated hard rule; a commit with a Chinese message
is not finished and must be amended before pushing:

```bash
git commit --amend            # fix the message, not the content
```

Use Conventional Commits — `type(scope): summary`, plus a bullet body when the change is not
self-evident.

```
fix(video): keep polling while the upstream task is not yet visible

- Treat 404 from /agnesapi as an intermediate state instead of a failure
- Exclude it from the consecutive-failure budget and from error_logs
```

Types in use: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `perf`, `ci`.
Scopes usually name the module: `video`, `image`, `chat`, `pipeline`, `subtitle`, `tts`, `web`,
`frontend`, `i18n`.

## 4. Before you push

```bash
bash scripts/preflight.sh            # mirrors CI; stops at the first failure
bash scripts/preflight.sh --full     # also runs the mock regression (slow)
```

Never push a red branch and let CI tell you. `references/testing.md` explains each check.

## 5. Opening the PR

```bash
git push -u origin fix/thing
gh pr create --repo lcy362/agnes-video-generator --fill
```

The PR body should answer four questions:

1. **What was wrong** — the symptom, with the user-facing message if there was one.
2. **Why** — the actual root cause, not the surface symptom. If the cause was upstream behaviour,
   cite the measured evidence.
3. **What changed** — the smallest description of the diff, and anything deliberately left alone.
4. **How it was verified** — the exact commands and scenario, plus the observed result.

Add a UI screenshot when the change is visible. Keep the description free of version numbers and
release-note wording — **releases are the maintainer's job** (`docs/dev/release_process.md`).

## 6. The hotfix path (from a troubleshooting dossier)

When the diagnosis phase hands over a defect:

1. **Confirm with the user before touching code.** Diagnosis and fixing are separate steps; the
   dossier is a proposal, not a mandate.
2. Reproduce it locally first — the dossier's evidence should let you reproduce without guessing.
3. Fix **one issue per PR**. If the dossier contains two defects, that is two PRs.
4. Verify with the specific path the dossier names (the endpoint, the scenario, the artifact), not
   just "the tests pass". A targeted check plus `preflight.sh` is the bar.
5. If reproduction fails, say so in the PR (or do not open one) rather than shipping a speculative
   guard. "Cannot reproduce on version X" is a useful outcome, not a failure.

## 7. Review etiquette

- Answer every review comment, even with "agreed, changed in <commit>" — the reviewer should not have
  to re-derive what happened.
- Push follow-up commits rather than force-pushing a branch under review; if a force-push is truly
  needed, say so in a comment.
- Keep the branch rebased on `upstream` so CI runs against current code.
- Do not close a reviewer's concern by reformatting unrelated code.

## 8. What not to do

- Do not bump the version or write release notes.
- Do not modify CI secrets, workflows' permission blocks, or the Sonar configuration.
- Do not commit credentials, generated media, or `static/` edits by hand (rebuild it — see
  `frontend-i18n.md`).

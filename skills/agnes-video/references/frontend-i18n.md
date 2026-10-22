# Frontend build and i18n

> Source anchor: upstream `AGENTS.md` §9, `frontend/vite.config.ts`, `frontend/package.json`,
> `.github/workflows/test.yml` (`frontend-build` job), `scripts/i18n_check.py`.
> Last verified: 2026-10-12.

## 1. Layout

| Path | Contents |
|------|----------|
| `frontend/src/components/` | Vue components (plus `forms/`, `presets/`, `shared/`) |
| `frontend/src/composables/` | `useConfig`, `useProgress`, `useTaskSubmit`, `useVoice`, `useGa`, … |
| `frontend/src/i18n/` | language packs and the `t()` implementation |
| `frontend/src/i18n/langs/*.json` | one file per language |
| `frontend/src/api/` | API client; sends the UI-language header |
| `frontend/src/utils/` | `feedback.ts`, `retryWindows.ts`, … |
| `static/` | **build output — shipped, committed, never hand-edited** |

## 2. The i18n contract

- **22 languages.** `zh` and `en` are preloaded; the other 20 are lazily `import()`ed.
- The key set is defined by `zh`. **`zh` and `en` must match 100%**; a missing `en` key is a defect,
  not a cosmetic issue.
- Other languages may lag; the checker lists what is missing, and `t()` falls back
  current language → `zh` → the key name. So a missing key shows up as Chinese text or a raw key.
- Every user-visible string goes through the i18n layer: buttons, placeholders, `title`, toasts,
  `alert()` text, error messages, empty states. **Hardcoded text — Chinese or English — is a defect.**

## 3. Adding or changing text

1. Add the key to `frontend/src/i18n/langs/zh.json` **and** `en.json`. Both, always, in the same PR.
2. Follow the existing naming style in the file you are editing; do not invent a parallel namespace.
3. If the text comes from the backend, it should be a message **key** the frontend renders, not a
   pre-rendered sentence — the backend emits `current_message_key` + `current_message_params` for
   exactly this reason.
4. Other languages can be filled later; do not machine-translate 20 files as part of an unrelated fix.

## 4. Checking

```bash
python scripts/i18n_check.py          # add --json for machine-readable output
```

Compares every language against `zh`. Exit codes: `0` complete, `1` missing keys (printed),
`2` a file failed to parse. The same script runs as the **first CI job** and as the pre-gate of the
large-version regression, where a failure stops the run.

## 5. Build output must be committed

```bash
cd frontend && npm run build
```

`npm run build` is `rm -rf ../static/assets && vue-tsc --noEmit && vite build`. Vite is configured
with `base: '/static/'`, `build.outDir: '../static'` and `emptyOutDir: false` — the last one is why
`favicon.ico`, `icon.png` and `generated/` survive the build. Do not "clean up" that setting.

`static/` is shipped to users by all three run modes, so it is committed. CI has a dedicated
`frontend-build` job that rebuilds the frontend and then fails if `git status --porcelain static/` is
non-empty:

> `static/` 产物与 `frontend/` 源码不一致，请运行 'cd frontend && npm run build' 后提交产物。

There is **no hook** preventing you from forgetting. The rule: **changed anything under
`frontend/src/` → rebuild → commit the output in the same commit.**

## 6. Backend / frontend message keys

- The backend resolves language per request (`X-Agnes-UI-Lang` → `Accept-Language` → `zh`) and per
  task (`state.ui_language`, frozen at creation so a task keeps one language).
- For messages that must render in all 22 languages, the backend sends a key and the frontend renders
  it; unmatched keys fall back to the pre-rendered `current_message`.
- Adding a backend message key that the frontend must render means adding the text to `zh.json` and
  `en.json` as well — and, for the queue-full guidance, keeping the 22-language set complete.

## 7. Checklist for a frontend change

```
[ ] text added to zh.json AND en.json (or no new text at all)
[ ] no hardcoded user-facing string introduced
[ ] python scripts/i18n_check.py → exit 0
[ ] npm test passes
[ ] npm run build succeeded
[ ] static/ changes are staged in the same commit
[ ] no hand-edit of static/ files
```

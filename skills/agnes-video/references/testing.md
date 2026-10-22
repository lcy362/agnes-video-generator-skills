# Testing

> Source anchor: upstream `pytest.ini`, `.github/workflows/test.yml`,
> `docs/dev/test_coverage_and_ci.md`, `scripts/run_mock_regression.sh`.
> Last verified: 2026-10-12.

## 1. Layout

| Path | Contents |
|------|----------|
| `tests/test_core.py` | pure units — models, subtitles, config, concatenation; no external dependency |
| `tests/test_audio_fallback.py` | shared audio fallback behaviour |
| `tests/mock_regression/` | integration framework: mock API, committed fixtures, pipeline tests |
| `tests/mock_regression/assets/` | sample `*.mp4` / `*.png` (committed — no generation step needed) |

Tests must **never** require the network or an API key: the mock regression replaces the Agnes video,
image and chat APIs, EdgeTTS and the rate limiter at the API boundary.

## 2. Running locally

```bash
.venv/bin/python -m pytest tests/ -q              # default: slow tests excluded (pytest.ini addopts)
.venv/bin/python -m pytest tests/ -q -m slow      # only the slow / real-media tests
.venv/bin/python -m pytest tests/ -o addopts="-ra -q"   # everything — what CI runs
.venv/bin/python -m pytest tests/test_core.py::test_name -q   # one test
```

`pytest.ini` sets `asyncio_mode = auto` (no per-test asyncio marker needed) and
`addopts = -ra -q -m "not slow"`. CI overrides `addopts` so the full suite — including slow,
real-media and real-timing tests — runs there. Never mark a test `slow` just to make it pass locally.

## 3. Coverage

```bash
.venv/bin/python -m pytest tests/ \
  --cov=core --cov=models --cov=utils --cov=web \
  --cov-report=term-missing --cov-fail-under=55
```

The gate is **55%** overall and applies to `core`, `models`, `utils` and `web` (the route layer is
included deliberately — it used to be missing). `scripts/` is excluded: those are one-off regression
tools. Dropping below the gate fails CI, so add tests rather than lowering it.

## 4. Mock regression

```bash
./scripts/run_mock_regression.sh              # all
./scripts/run_mock_regression.sh simple|creative|manuscript|anchor|resume|clean|check
```

`check` validates the mock environment without running scenarios; `clean` clears its output. Run at
least `all` after touching a pipeline, the compositor, subtitles or TTS; it is the cheapest way to
catch a broken pipeline before CI does. It needs no API key and no network.

## 5. Lint

```bash
ruff check core/ web/ utils/ models/ scripts/ --output-format=github
```

Config lives in `ruff.toml`. CI fails on findings, so run it before pushing.

## 6. Frontend

```bash
cd frontend && npm ci --ignore-scripts
cd frontend && npm test        # vitest run
cd frontend && npm run build   # rm -rf ../static/assets && vue-tsc --noEmit && vite build
```

## 7. What to run for which change

| You changed | Minimum | Also |
|-------------|---------|------|
| A pure function / model | `pytest tests/test_core.py` + a new test | — |
| A pipeline step | `run_mock_regression.sh all` | targeted unit tests, then the matching real scenario |
| Subtitles / TTS | `run_mock_regression.sh` (timeline, end-frame, watermark paths) | `pytest -m slow` |
| An API client / retry policy | `tests/test_upstream_error_handling.py` | `run_mock_regression.sh all` |
| A route or response shape | `pytest tests/` with `--cov=web` | endpoint check via curl |
| User-visible text | — | `python scripts/i18n_check.py` and the i18n rules |
| `frontend/src/` | `npm test` | `npm run build` **and commit `static/`** |
| Anything pipeline-wide | `preflight.sh --full` | the regression matrix (`regression.md`) |

## 8. Writing tests

1. Name files `test_*.py`, functions `test_*`; `tests/` is the only test path.
2. Mock at the **API boundary** (video/image/chat clients, TTS, rate limiter) so no network or key is
   needed — follow the patterns in `tests/mock_regression/`.
3. Commit any new fixture (media or text) into `tests/mock_regression/` so a fresh checkout can run.
4. For a bug fix, add the test that fails on the old code first. A fix without a reproducing test is
   an unfinished fix.
5. Prefer asserting behaviour over implementation detail: assert the produced artifact, the response
   body, or the emitted message key.

## 9. Anti-patterns

- Tests that need a real API key or the network — they are useless in CI and hostile locally.
- Marking tests `slow` to dodge failures.
- Widening tolerance ranges in an assertion to make it pass.
- Asserting on `perf_params` or any internal upstream field instead of the produced artifact.

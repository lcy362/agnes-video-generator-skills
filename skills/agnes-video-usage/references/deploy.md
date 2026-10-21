# Deploying and configuring the service

> Source anchor: upstream `docs/public/getting-started.md`, `AGENTS.md` §0, `docs/public/faq.md`,
> `bin/cli.js`. Last verified: 2026-10-21 against upstream v7.2.1.

> **Agent path (preferred):** `python3 scripts/bootstrap.py install --yes --json` covers §0 end to end —
> installation under `$AGNES_HOME`, its own venv, start, workspace wiring, and the key check. The manual
> steps below are for teaching a human, debugging the bootstrap, or the deliberate route A (changing code).
> Directory layout, state machine and exit codes: `bootstrap-contract.md`.

## 0. From zero: onboarding

Goal: a service that passes the four-layer verification **and** writes videos into the folder the user
wants. Do these steps in order and report at the end; do not skip the verification.

**Step 1 — probe the environment, then pick a route.**

```bash
python3 --version ; docker --version ; node --version ; ffmpeg -version | head -1
```

| Environment | Route |
|-------------|-------|
| Node 18+ and Python 3.10+ (the common case) | **C — npm, default** (no clone; `bootstrap.py` or `npx free-short-video`) |
| Docker present, no Python, user does not want to manage ffmpeg | B — Docker |
| User wants to change the code | A — manual (`git clone` + `./start.sh`) |
| No Python 3.10+, no Docker, no Node | Stop and help the user install one of them first — do not improvise |

**Step 2 — decide where the data lives.** With routes B and C nothing is cloned, so the only path to
agree on is the workspace: `$AGNES_HOME/workspace` by default, or the folder the user wants to browse
(`AGNES_OUTPUT_DIR` gets a copy of each deliverable, §4).

**Step 3 — install.** Default route C (no clone, no system ffmpeg):

```bash
python3 scripts/bootstrap.py install --yes --json   # agent path: own venv, start, workspace
```

Manual equivalent (what the script does under the hood — note the venv lives in `$AGNES_HOME`, not in
the package directory, so a version bump never re-downloads Python dependencies):

```bash
export AGNES_HOME="$HOME/.agnes-video"
npm install --prefix "$AGNES_HOME/runtime" free-short-video@latest
python3 -m venv "$AGNES_HOME/venv"
"$AGNES_HOME/venv/bin/pip" install -r "$AGNES_HOME/runtime/node_modules/free-short-video/requirements.txt"
AGNES_CONFIG_DIR="$AGNES_HOME/config" PORT=8765 \
  "$AGNES_HOME/venv/bin/python" "$AGNES_HOME/runtime/node_modules/free-short-video/server.py"
```

Route A (only when the user wants to work on the code):

```bash
git clone https://github.com/lcy362/agnes-video-generator.git
cd agnes-video-generator && ./start.sh
```

**Step 4 — configure the API key.** Ask the user for it; free keys come from
<https://platform.agnes-ai.com>.

```bash
curl -X POST http://localhost:8765/api/config -F 'api_key=...'   # endpoint expects form data
curl -X POST http://localhost:8765/api/config/keys/detect        # bind the key to its domain
curl -s http://localhost:8765/api/models > /dev/null            # cheap proof the key works
```

The agent path is `python3 scripts/bootstrap.py config-key` with the key on stdin (no argv, no echo);
the preferred path is still the user pasting it into the local web UI themselves.

Never invent a key, never print it back in full, and never write it into a file that could be
committed. If a `401` follows, read §3 before changing anything — the key is probably bound to a
different site than the configured domain.

**Step 5 — point the workspace** at the folder from step 2 (`§4` settings), so outputs appear where
the user expects.

**Step 6 — verify, then prove it end to end.**

```bash
bash scripts/verify_deploy.sh
```

Then submit one throwaway task of each type the user intends to use and confirm it reaches
`completed` (§5). Report: route chosen, where the project lives, where videos will appear, and the
verification result.

## 1. Four deployment routes

| Route | When | Command |
|-------|------|---------|
| **C — npm (default)** | Node 18+ and Python 3.10+, the common case | `python3 scripts/bootstrap.py install --yes` (own venv, stable paths) or `npx free-short-video@7.2.1 --detach --json` |
| B — Docker | No Python / no ffmpeg on the host | `docker run -d -p 8765:8765 -v ~/.agnes-video/config:/app/.agnes_config -v ~/.agnes-video/workspace:/app/.working_dir lcy362/free-short-video:7.2.1` |
| A — manual | The user wants to change the code | `git clone` + `./start.sh` (creates `.venv`, installs deps, starts on 8765) |

> Since upstream **v7.2.1** the npm launcher has the same properties: data root under `~/.agnes-video`
> (`AGNES_HOME` / `--home`), dependencies installed once (requirements fingerprint), and
> `--detach` / `--json` / `--print-paths` for scripts. `bootstrap.py` still owns its own venv and
> `server.py` spawn so that every supported install — npm at any version, Docker, clone — behaves
> identically, and so upgrades keep working even if the package layout changes again.
>
> Upgrading an older npm install: the launcher copies a legacy in-package `.agnes_config` into the new
> data root on first run, so the configured key survives; previously generated videos are not moved.

Requirements: Python 3.10+. ffmpeg is only needed for route A; Docker and npm bundle it
(`imageio-ffmpeg`), and a system ffmpeg on `PATH` takes precedence over the bundled one.

## 2. API key

```bash
export AGNES_API_KEY="your-api-key"                      # env, read at startup
curl -X POST http://localhost:8765/api/config -F 'api_key=your-api-key'   # form data, not JSON
```

Several keys: name them `AGNES_API_KEY`, `AGNES_API_KEY_2`, `AGNES_API_KEY_3` … numbering must be
contiguous. Rate-limit quotas scale with the key count and a `429` rotates to the next key.

## 3. The domain trap that produces `401`

Agnes serves separate sites; a `401 invalid token` is almost always a key sent to the wrong one:

| Domain | Accepts keys from |
|--------|-------------------|
| `apihub.agnes-ai.com` (global, default) | the global site |
| `api.agnes-ai.cn` (China) | China-domestic-only keys |
| `apihub.agnes-ai.cn` (fallback) | both |

The domain is chosen on the **Web config page**, not in `.env`:

- Keys from `AGNES_API_KEY*` environment variables are **env keys** — they cannot carry a per-key
  domain and are **skipped by "Auto-detect domains"**. They all use the single global default domain.
- Keys added on the config page are **config keys** — each has its own domain dropdown or can be
  auto-detected, and they persist across restarts.

So: one key from one site → just set the global default domain to match. Keys from different sites
mixed together → add them on the config page instead of via env. With rotation, a single mismatched
key makes tasks fail intermittently with `401` whenever it is picked.

## 4. Other configuration

| Setting | How |
|---------|-----|
| Workspaces | `GET/POST/DELETE /api/workspaces`, activate with `POST /api/workspaces/active` |
| Models | `GET /api/models`, save with `POST /api/config/models` |
| Pluggable text LLM | `POST /api/config/text-providers` (OpenAI- or Anthropic-compatible), then `POST /api/config/models` with `text_provider` |
| Watermark | `POST /api/config/watermark` |
| CORS for companion tools | `AGNES_CORS_ORIGINS=http://localhost:8787` (disabled by default, same-origin unaffected) |
| Large models / prompts | see upstream `.env.example` for every supported variable |

Text providers are stored in the local `config.json` (`0600`) and always returned masked; an empty
`api_key` on update keeps the stored one. The built-in `agnes` provider is always first and cannot
be deleted.

## 5. Verify the deployment

```bash
bash scripts/verify_deploy.sh                     # the four-layer checklist, one command
# or by hand:
curl -s -o /dev/null -w "%{http_code}\n" http://localhost:8765/
curl -s http://localhost:8765/api/config | python3 -m json.tool
curl -s http://localhost:8765/api/voices | python3 -m json.tool     # voices grouped per language
curl -s http://localhost:8765/api/tasks  | python3 -m json.tool
```

Then create one throwaway task per type you intend to use (see `task-types.md`) and confirm it
reaches `completed`.

## 6. Common startup problems

| Symptom | Cause |
|---------|-------|
| Port 8765 already in use | Another instance is running; `lsof -i :8765` |
| `FileNotFoundError: 'ffmpeg'` **at generation time**, not startup | Relied on the bundled binary and it failed to install/extract — install a system ffmpeg |
| Chinese subtitles render as boxes | CJK font missing from `resource/fonts/` and no system fallback |
| Every task `401` | Key/domain mismatch (§3) |
| Server starts but tasks stay `pending` | No active pipeline after a restart — call `POST /api/tasks/{id}/resume` |

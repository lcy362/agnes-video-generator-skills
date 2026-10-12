# Deploying and configuring the service

> Source anchor: upstream `docs/public/getting-started.md`, `AGENTS.md` §0, `docs/public/faq.md`.
> Last verified: 2026-10-12 against upstream v7.5 docs.

## 0. From zero: onboarding

Goal: a service that passes the four-layer verification **and** writes videos into the folder the user
wants. Do these steps in order and report at the end; do not skip the verification.

**Step 1 — probe the environment, then pick a route.**

```bash
python3 --version ; docker --version ; node --version ; ffmpeg -version | head -1
```

| Environment | Route |
|-------------|-------|
| Python 3.10+ present, user may work on the code | A — manual (`./start.sh`) |
| Docker present, user does not want to manage Python or ffmpeg | B — Docker |
| Node 18+ and Python 3.10+, user wants a one-command install | C — npm (`npx free-short-video`) |
| No Python 3.10+ and no Docker | Stop and help the user install one of them first — do not improvise route A |

**Step 2 — decide where the project and its data live.** Ask the user where they want the repository
cloned and where generated videos should land. The workspace is not necessarily the clone directory;
it is configurable (§4) and is what the user will browse for finished videos. Confirm the path.

**Step 3 — clone and install.**

```bash
git clone https://github.com/lcy362/agnes-video-generator.git
cd agnes-video-generator && ./start.sh          # route A
```

`start.sh` creates the venv, installs dependencies and serves `http://localhost:8765`. For routes B
and C see §1 — neither needs a system ffmpeg.

**Step 4 — configure the API key.** Ask the user for it; free keys come from
<https://platform.agnes-ai.com>.

```bash
curl -X POST http://localhost:8765/api/config \
  -H "Content-Type: application/json" -d '{"api_key": "..."}'
```

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
| A — manual | You have Python and want to work on the code | `./start.sh` (creates the venv, installs deps, starts on 8765) |
| B — Docker | No Python / ffmpeg on the host | `docker run -d -p 8765:8765 -e AGNES_API_KEY=<key> -v ~/agnes-data/working:/app/.working_dir -v ~/agnes-data/config:/app/.agnes_config lcy362/free-short-video:latest` |
| C — npm | One command, no clone | `AGNES_API_KEY=<key> npx free-short-video` (options: `--port`, `--host`, `--no-open`) |
| D — agent-assisted | Hand the whole thing to an agent | Tell it to read upstream `AGENTS.md`, install deps, set the key, start the server |

Manual equivalent of `start.sh`:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python server.py
```

Requirements: Python 3.10+. ffmpeg is only needed for route A; Docker and npm bundle it
(`imageio-ffmpeg`), and a system ffmpeg on `PATH` takes precedence over the bundled one.

## 2. API key

```bash
export AGNES_API_KEY="your-api-key"                      # env, read at startup
curl -X POST http://localhost:8765/api/config \
  -H "Content-Type: application/json" -d '{"api_key": "your-api-key"}'   # or via API / Web UI
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

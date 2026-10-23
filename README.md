# PokeSim Agent

A fork of [PokeSim](https://github.com/afk-sapien/PokeSim) rebuilt around a
local web dashboard, a PyBoy emulator, and an optional **OpenAI-compatible
vision agent** that watches the screen and plays Pokémon one short button
sequence at a time.

The important difference: **AI is chosen per game**, and the built-in
**Default** autopilot is the default option. You can run entirely offline with
no model endpoint, point one game at a local Ollama model and another at a
hosted vision model, or switch any game to manual control.

> Bring your own ROM. This project does not include Pokémon ROMs or game data.
> It is intended for personal use with games you legally own.

---

## Features

- **Per-game AI selector** in the header:
  - `Default` — built-in local autopilot, no API key needed (default)
  - `Vision agent` — OpenAI-compatible vision model
  - `Manual only` — play with the on-screen pad or keyboard
- **Live 160×144 canvas** streamed over a WebSocket.
- **Live game state**: trainer, location, coordinates, badges, money, play
  time, Pokédex counts, battle state, party HP/levels/status/moves.
- **Agent dashboard**: current thought, multi-step plan, last actions, rolling
  memory, structured event log.
- **Take control / hand over** at any time. Pressing a control takes over
  immediately and cancels the agent's in-flight action.
- **Pause / resume** and **clear memory**.
- **Settings drawer**: base URL, API key, model ID, poll interval, context
  window, image history, action/frame limits, temperature, timeout, endpoint
  test, and optional per-game endpoint overrides.
- **Demo mode**: with no ROM mounted, a procedural demo game still exercises
  the full emulator, canvas, controller, memory, and agent pipeline.
- **Docker + Compose** deployment with read-only ROM mounts and writable data.

## How it works

```
Browser (canvas + dashboard)
   │  REST for control, WebSocket for frames/state
   ▼
FastAPI ──► GameSession ──► EmulatorWorker thread ──► PyBoy / demo emulator
                │
                ├── RollingMemory ──► system prompt + state + screenshots
                └── AgentController ──► DefaultPolicy or VisionClient
                                             │
                                             ▼
                                  OpenAI-compatible /chat/completions
```

PyBoy is not thread-safe. Exactly one worker thread touches the emulator; all
manual presses and agent sequences are queued there. See
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the protocol and data layout.

## Quick start (local)

Requires Python 3.11–3.12. PyBoy may not have wheels for very new Python
releases; the Docker image uses Python 3.12.

```bash
git clone <your-fork-url> PokeSim-Agent
cd PokeSim-Agent

python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,emulator]"

cp .env.example .env        # optional; defaults are sensible
python -m app
```

Open <http://127.0.0.1:8000>. With an empty `roms/` directory you will get the
**Pokémon Demo** and the default autopilot will start playing.

To use a real game, put a `.gb`/`.gbc` file (or a `.zip` containing one) in
`roms/`, then click **Rescan** in the header (or restart the app). ROMs remain
untouched; extracted copies and PyBoy saves go under
`data/games/<game-id>/`.

### Vision agent setup

1. Start any OpenAI-compatible server. Examples:

   | Server | Base URL | Example model |
   | --- | --- | --- |
   | Ollama | `http://localhost:11434/v1` | `llava` |
   | LM Studio | `http://localhost:1234/v1` | `qwen2-vl-7b-instruct` |
   | vLLM | `http://localhost:8000/v1` | `llava-hf/llava-1.5-7b-hf` |
   | OpenAI | `https://api.openai.com/v1` | `gpt-4o-mini` |

2. Open **Settings**, choose a preset or enter the base URL and model, and
   press **Test endpoint**.
3. Select **Vision agent** in the per-game **AI player** dropdown. The choice
   is saved for that game and survives restarts.

`/v1` is appended when omitted, and a URL ending in `/v1` gets
`/chat/completions` appended. The client only assumes the standard
`/chat/completions` contract and the OpenAI `image_url` content part.

## Docker

### Run the published image (no source checkout)

Every push to `main` and every `v*` tag is built by
[`.github/workflows/docker-publish.yml`](.github/workflows/docker-publish.yml)
and published to GitHub Container Registry as
`ghcr.io/billbutter/pokesim-agent:latest`.

On any machine with Docker:

```bash
mkdir -p roms data
# put .gb/.gbc files in ./roms (mounted read-only)
curl -fsSLO https://raw.githubusercontent.com/BillButter/PokeSim-Agent/main/docker-compose.ghcr.yml
docker compose -f docker-compose.ghcr.yml up -d
docker compose -f docker-compose.ghcr.yml logs -f
```

No Python, ROM tooling, or local build is needed. The compose file accepts
these environment overrides:

| Variable | Default | Purpose |
| --- | --- | --- |
| `POKESIM_IMAGE` | `ghcr.io/billbutter/pokesim-agent:latest` | Image/tag to run |
| `POKESIM_HOST_BIND` | `127.0.0.1` | Host bind address |
| `POKESIM_HOST_PORT` | `8000` | Host port |
| `POKESIM_ROMS_PATH` | `./roms` | Host ROM directory |
| `POKESIM_DATA_PATH` | `./data` | Host data directory |
| `POKESIM_UID` / `POKESIM_GID` | `1000` | Container user (see below) |

The GHCR package is public, so anonymous `docker pull` works. The image is
built for `linux/amd64`.

### Build locally

```bash
cp .env.example .env
# put ROMs in ./roms (mounted read-only)
docker compose up --build -d
docker compose logs -f
```

Open <http://127.0.0.1:8000>. The Compose file publishes the port on loopback
only.

When the model server runs on the host, use
`AI_BASE_URL=http://host.docker.internal:11434/v1`; Compose adds the required
`host-gateway` mapping. Data written by the container lands in `./data`. If
your host user is not UID/GID 1000, set `POKESIM_UID`/`POKESIM_GID` in `.env`
and uncomment the `user:` line in `docker-compose.yml`.

The image installs SDL2 runtime libraries, runs PyBoy with `window="null"`, and
uses `SDL_VIDEODRIVER=dummy`—no X server is required. PyBoy is installed through
the `emulator` extra. The web UI still works without PyBoy (demo mode), but
real ROMs need it.

### Podman Quadlet with registry auto-updates

[`deploy/pokesim-agent.container`](deploy/pokesim-agent.container) runs the same
published image as a systemd service with `AutoUpdate=registry`. Podman's
`podman-auto-update.timer` checks `ghcr.io/billbutter/pokesim-agent:latest`,
pulls new digests, and restarts the service automatically.

```bash
mkdir -p ~/pokesim/{roms,data} ~/.config/containers/systemd
cp deploy/pokesim-agent.container ~/.config/containers/systemd/
systemctl --user daemon-reload
systemctl --user start pokesim-agent.service
systemctl --user enable --now podman-auto-update.timer
```

See [`deploy/README.md`](deploy/README.md) for rootful installation, AI
credential drop-ins, pinning a version tag, and update verification.

## Configuration

Environment variables are read at startup. AI values can also be changed in
the UI and are persisted to `data/settings.json`. See
[`.env.example`](.env.example) for the full list.

| Variable | Default | Purpose |
| --- | --- | --- |
| `POKESIM_HOST` | `127.0.0.1` | Bind address |
| `POKESIM_PORT` | `8000` | HTTP/WebSocket port |
| `POKESIM_ROMS_DIR` | `roms` | ROM search directory (recursive) |
| `POKESIM_DATA_DIR` | `data` | Settings, profiles, saves |
| `POKESIM_DEMO_GAME` | `true` | Create a demo when no ROMs exist |
| `POKESIM_FRAME_FPS` | `12` | Stream frame cap |
| `POKESIM_EMULATION_SPEED` | `0` | `0` unlimited, `1` real time |
| `POKESIM_DEFAULT_AI_MODE` | `default` | Mode for new profiles |
| `AI_BASE_URL` | `http://localhost:11434/v1` | Model API root |
| `AI_MODEL` | `llava` | Model ID |
| `AI_API_KEY` | empty | Bearer token, optional for local servers |
| `AI_POLL_INTERVAL` | `4` | Seconds between vision turns |
| `AI_MAX_CONTEXT_TURNS` | `8` | Rolling turns kept in context |
| `AI_IMAGE_HISTORY` | `2` | Previous screenshots resent |
| `AI_MAX_ACTIONS` | `8` | Max actions per decision |
| `AI_MAX_FRAMES` | `240` | Max frames per action |
| `AI_TEMPERATURE` | `0.2` | Sampling temperature |
| `AI_TIMEOUT` | `120` | Request timeout in seconds |

### AI modes and overrides

Each game profile stores `ai_mode` (`default`, `vision`, or `manual`) and an
optional `overrides` object. Overrides are merged over the global AI settings,
so you can run one game against a local model and another against a hosted one.
Clearing an override field makes that game inherit the global value again. The
**Clear game overrides** button applies immediately.

Default is deliberately the first option in the dropdown and the default for
newly discovered games, ROMs, and the demo.

### Choosing a model

A vision-capable model is required for the `vision` mode. Text-only models can
answer, but they will be playing blind. Small 7B vision models are usable for
short reactions; expect frequent menu mistakes. The agent is deliberately
limited to short, reversible button sequences and re-observes after each turn.

## API

Interactive docs are available at <http://127.0.0.1:8000/docs>.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/health` | Health, version, PyBoy availability |
| `GET` | `/api/games` | Games, global AI settings, mode list |
| `GET` | `/api/games/{id}` | Full snapshot + frame + memory |
| `POST` | `/api/games/{id}/start` | Start emulator and agent |
| `POST` | `/api/games/{id}/stop` | Save and stop |
| `PATCH` | `/api/games/{id}` | Rename, AI mode, per-game overrides |
| `POST` | `/api/games/{id}/control` | `take_control`, `handover`, `pause`, `resume` |
| `POST` | `/api/games/{id}/input` | `{button, action, frames}` |
| `POST` | `/api/games/{id}/agent/reset` | Clear rolling memory |
| `GET` | `/api/games/{id}/events` | Event log |
| `POST` | `/api/roms/refresh` | Rescan ROM directory |
| `GET`/`PUT` | `/api/settings` | Read/update global AI settings |
| `POST` | `/api/settings/test` | Test an endpoint (`GET /v1/models`) |
| `WS` | `/ws/games/{id}` | `hello`, `frame`, `state`, `agent`, `memory`, `events`, `ping` |

The API key is never returned by `GET /api/settings`; only `has_api_key` is
exposed. `data/settings.json` is written with mode `0600`.

## Keyboard

| Action | Keys |
| --- | --- |
| Move | arrow keys |
| A | `Z` or `K` |
| B | `X` or `J` |
| Start | `Enter` |
| Select | `Shift` |

Any manual input takes control first; the agent's current action is cancelled
before the new command is queued.

## Testing

```bash
pip install -e ".[dev]"
pytest
```

The test suite uses the mock emulator and an `httpx.MockTransport` model client,
so it needs neither a ROM nor a model endpoint. PyBoy-specific paths are only
exercised when PyBoy is installed.

## Security and limitations

- **No authentication.** Bind to loopback (the default) or put the app behind a
  reverse proxy with auth. Do not expose it directly to the internet.
- The dashboard can control the emulator and read game state. Treat it like a
  local admin tool.
- API keys are stored in plaintext in `data/settings.json` (mode `0600`). The UI
  never displays a saved key again.
- Generation I (Red/Blue/Yellow) state decoding is implemented. Other
  generations still emulate but show a mostly empty state panel.
- The Default policy is a small demonstrator, not a speedrunner. Vision models
  can be slow, expensive, and wrong; action limits and polling protect the
  session rather than guaranteeing good play.
- Pokémon and related names are trademarks of Nintendo / Creatures / GAME
  FREAK. This project ships no ROMs or extracted game assets.

## Project layout

```
app/
  main.py            FastAPI app, REST routes, WebSocket
  session.py         GameSession, emulator worker, handover
  emulator.py        PyBoy backend + procedural demo
  manager.py         ROM discovery, profiles, session registry
  config.py          Environment settings and AI config
  store.py           Atomic JSON persistence
  models.py          Pydantic API models
  gen1.py            Gen 1 WRAM reader and state deltas
  gen1_data.py       Generated species/map tables
  agent/
    client.py        OpenAI-compatible HTTP client
    controller.py    Default and vision control loops
    parser.py        Tolerant structured-JSON decision parser
    memory.py        Rolling context and prompt assembly
    prompts.py       System prompt and observation formatting
  static/            Dashboard (HTML/CSS/JS)
docs/                Architecture notes
tests/               Pytest suite
```

## License

MIT. See [LICENSE](LICENSE). Third-party notices are in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md). The fork builds on PokeSim;
upstream copyright and attribution are retained.

# Agent architecture

This fork keeps PokeSim's upstream Adventure Library, emulator workers, strategic
autopilot and per-adventure settings. It adds an optional feature: each adventure
can choose which player drives the emulator.

| `ai_mode` | Player | Network | Config |
| --- | --- | --- | --- |
| `default` | Upstream PokeSim `StrategicPolicy` (the original autopilot) | None | None |
| `vision` | OpenAI-compatible vision agent | Model endpoint | `AI_BASE_URL`, `AI_MODEL`, `AI_API_KEY` |
| `gemini` | Google Gemini vision agent | Google API | `GEMINI_API_KEY`, optional `GEMINI_BASE_URL`, `GEMINI_MODEL` |
| `ml` | Local decision-tree machine learning player | None | None |
| `manual` | Keyboard and on-screen controls only | None | None |

`default` is first in every selector and is the fallback for old adventures that
have no stored `ai_mode`.

## Process model

The upstream architecture is unchanged:

```
browser ──HTTP/WebSocket── FastAPI app (pokesim.app.manager)
                              │
                              ├── Supervisor ── child process per adventure
                              │                     │
                              │                     └── runtime/worker.py
                              │                           ├── Gen I emulator
                              │                           └── Gen II emulator
                              │
                              └── shared Assets / Registry under DATA_DIR
```

Each adventure runs in its own worker process. The worker owns exactly one
emulator thread; the FastAPI process never touches the emulator's PyBoy object
directly. The supervisor starts, monitors, and reconciles workers.

## Where the agents sit

All agents are implemented under `pokesim/agent/`:

### Vision and Gemini agents (remote models)

- `config.py` reads server-wide configuration (`AI_*`, `GEMINI_*`).
- `client.py` posts to an OpenAI-compatible `/chat/completions` endpoint.
- `parser.py` validates the structured decision JSON.
- `memory.py` keeps a bounded rolling conversation.
- `prompts.py` builds the system prompt and compact state text.
- `runner.py` runs one observation/decision loop per adventure.
- `goals.py` injects optional per-adventure goals into prompts.

When an adventure's `ai_mode` becomes `vision` or `gemini`, the emulator starts a
`VisionAgentRunner` thread. The runner does not press buttons itself. It:

1. captures a snapshot and a 160x144 RGB image through `Emulator.call()`, so the
   read happens on the emulator thread;
2. sends the screenshot, compact state, state delta, plan and recent memory to the
   remote model (with optional goals injected);
3. parses a short list of `(buttons, frames)` actions;
4. queues that list on the emulator's `agent_actions` queue.

### ML agent (local learning)

- `ml_player.py` implements decision-tree logic for autonomous gameplay.
- `ml_runner.py` runs the observation/decision loop locally without network.
- Learns from gameplay patterns and decision outcomes.
- Makes decisions for battles (wild, trainer) and overworld exploration.
- No external dependencies or API keys required.

When an adventure's `ai_mode` becomes `ml`, the emulator starts an
`MLAgentRunner` thread. It captures game state and uses the ML player to decide
actions without contacting any remote service.

### Shared behavior

The emulator's normal control loop consumes one queued action at a time exactly
like a policy action, then publishes frames and state as usual. While any agent
is thinking, the game waits rather than running a different policy underneath it.

Switching modes is live:

- `default` clears queued agent actions and returns to the upstream policy.
- `vision` or `gemini` clears queued actions and starts or resumes the remote agent.
- `ml` clears queued actions and starts or resumes the local learner.
- `manual` clears queued actions and leaves the emulator waiting for input.

Pause, take control, resume, restart and worker reconciliation all clear the
agent queue. Taking control pauses any agent; resuming returns to the mode
stored for that adventure.

## Decision format

The model returns one JSON object:

```json
{
  "thought": "The north exit of Pallet Town is clear.",
  "plan": ["Walk north to Route 1", "Cross the grass", "Reach Viridian City"],
  "actions": [
    {"buttons": ["up"], "frames": 24},
    {"buttons": ["a"], "frames": 4}
  ],
  "memory": "Oak's lab is south of here.",
  "done": false
}
```

The parser accepts fenced JSON, leading prose, a single action object, common key
aliases, and `{"up": 12}`-style maps. Invalid output is surfaced as an agent error
in the dashboard. The runner waits, then asks again; it never silently substitutes
a different player.

## Configuration

### Remote agent endpoints

Endpoints are server-wide, because API keys should not be stored in adventure
records:

| Variable | Meaning |
| --- | --- |
| `AI_BASE_URL` | OpenAI-compatible base URL, e.g. `http://localhost:11434/v1` |
| `AI_API_KEY` | Optional bearer token for vision endpoint |
| `AI_MODEL` | Vision-capable model name (required for vision mode) |
| `AI_POLL_INTERVAL` | Seconds between observations (default 4) |
| `AI_MAX_CONTEXT_TURNS` | Rolling text turns (default 8) |
| `AI_IMAGE_HISTORY` | Recent screenshots reattached (default 2) |
| `AI_MAX_ACTIONS` | Actions per decision (default 8, max 12) |
| `AI_MAX_FRAMES` | Frames per action (default 120, max 240) |
| `AI_TEMPERATURE` | Sampling temperature (default 0.2) |
| `AI_TIMEOUT` | Request timeout in seconds (default 120) |

| Variable | Meaning |
| --- | --- |
| `GEMINI_API_KEY` | Google Gemini API key (required for gemini mode) |
| `GEMINI_BASE_URL` | Optional custom Gemini endpoint base URL |
| `GEMINI_MODEL` | Model name (default `gemini-2.5-flash`) |

### Local ML agent

The ML agent requires no configuration. It runs entirely locally with no network
calls or external dependencies. Enable it by selecting `ml` mode in adventure
settings.

### Per-adventure goals

Optional per-adventure goals (max 2000 chars) guide vision and Gemini agents:

| Variable | Meaning |
| --- | --- |
| `ai_goals` | String of goals, one per line (stored in adventure settings) |

Goals are formatted as a bullet list and injected into the system prompt for
vision and Gemini agents. Leave empty for fully autonomous play.

### Mode selection

Each managed adventure defaults to `default`; its selected AI player is stored
in the upstream adventure settings and can be changed while the adventure runs.
The standalone runtime also accepts `AI_MODE`, but the managed library does not
use it.

A missing endpoint or model is not fatal. The library still works, `default`,
`ml`, and `manual` adventures always run. A vision or gemini adventure reports
the configuration error in its dashboard if the endpoint is unavailable.

## API additions

- `GET /api/v1/settings` includes an `agent` object with the public AI
  configuration (never the API key).
- `POST /internal/ai_mode` is the worker-private endpoint used by the supervisor
  to switch a running adventure.
- Adventure create and edit payloads accept `ai_mode` at the top level or inside
  `settings`.

## Persistence

The agent does not add its own database. `ai_mode` lives in the adventure's
upstream settings record. The rolling conversation is in memory only, so a worker
restart starts with a fresh context. Saves and autosaves remain upstream's.

```
DATA_DIR/
  registry / adventures / assets / logs     # upstream layout
  assets/reference/<revision>/              # generated game data
  assets/roms/<sha256>/rom.gb                # imported cartridges
  adventures/<id>/                           # worker saves and checkpoints
```

`ROM_DIR` is scanned at manager startup and every supported `.gb`, `.gbc` or
`.zip` is imported through the same verified cartridge path as an upload. The
mount can stay read-only.

## Security

The library is an admin surface with no authentication. It can run a local
emulator and send screenshots to the configured model endpoint. Keep the bind on
`127.0.0.1` or put it behind an authenticated reverse proxy. Keep `AI_API_KEY` in
the container environment or a secret drop-in, not in an adventure name or ROM
folder.

# Architecture

This document describes the runtime design, the WebSocket protocol, the agent
decision format, and the on-disk layout.

## Goals

1. Keep the emulator deterministic and single-threaded.
2. Let the browser render frames without blocking gameplay or the agent.
3. Make the AI layer optional and swappable per game.
4. Survive missing ROMs, missing model endpoints, and unsupported game
   generations without taking down the dashboard or losing saved settings.

## Process and thread model

```
┌────────────────────────────── FastAPI / asyncio ──────────────────────────────┐
│                                                                              │
│  REST routes ──► GameManager ──► GameSession                                  │
│                                      │                                       │
│                                      ├── AgentController (asyncio.Task)      │
│                                      │      ├── DefaultPolicy                 │
│                                      │      └── VisionClient (httpx)          │
│                                      │                                       │
│                                      ├── RollingMemory (thread-safe deque)    │
│                                      └── frame/state/agent revisions         │
│                                                                              │
│  WebSocket ──► polls revisions every 50 ms ──► pushes changed payloads       │
└───────────────────────────────────┬──────────────────────────────────────────┘
                                    │ queue.Queue[Command]
                                    ▼
┌──────────────────── EmulatorWorker (one daemon thread per game) ─────────────┐
│  owns PyBoy / MockEmulator                                                  │
│  loop: pause? → drain one command or tick one frame → pace to 60 fps        │
│  captures PNG at frame_fps, snapshots state every ~0.35 s                   │
└─────────────────────────────────────────────────────────────────────────────┘
```

PyBoy must only be touched by one thread. Every manual button, agent sequence,
and tick is a `Command` placed on the worker's queue. Commands carry a
`threading.Event` cancel token. Taking control or stopping sets the active
token, so a long walk is interrupted before the next frame.

The browser is a passive observer over the WebSocket. Manual input and control
changes go through REST so they can be acknowledged and validated.

### Session lifecycle

- `GameSession` is created for every stored profile when `GameManager` starts.
- `start()` builds the emulator in a worker thread via `asyncio.to_thread`,
  starts `EmulatorWorker`, then starts `AgentController` unless the mode is
  `manual` or the game is paused.
- `take_control()` sets `manual=True`, cancels the emulator's active command,
  and cancels the agent task.
- `handover()` clears `manual` and starts a fresh controller. A game left in
  `manual` mode is promoted to `default` on handover.
- `pause()` pauses the worker (frame capture continues slowly) and stops the
  agent. `resume()` restarts it according to the mode.
- `stop()` cancels the agent, stops the worker, closes PyBoy with
  `save=True`, and clears the runtime state.

### Failure handling

- Emulator construction failures set `status="error"` and are reported as
  HTTP 400/409 while the session stays selectable.
- A fatal worker exception calls `session.fail()`, resolves queued futures, and
  is logged. A new `start()` can rebuild the emulator.
- Vision errors are shown in the agent panel. Up to two consecutive failures
  produce a small fallback action (press A) to keep the game responsive; later
  failures back off and wait for settings changes.
- Endpoint settings changes restart running agents so a corrected URL is used
  immediately, without restarting the emulator.
- Gen 1 reads are defensive: bad addresses return zeroes, and a snapshot with
  an error still renders the dashboard.

## Per-game AI selection

Each game profile in `data/games.json` contains:

```json
{
  "id": "pokemon-red-1a2b3c4d5e",
  "name": "Pokémon Red",
  "title": "POKEMON RED",
  "rom": "/absolute/path/to/red.gb",
  "demo": false,
  "ai_mode": "default",
  "overrides": {
    "base_url": "http://localhost:11434/v1",
    "model": "llava",
    "poll_interval": 4
  }
}
```

`ai_mode` is one of:

| Mode | Behavior |
| --- | --- |
| `default` | Local `DefaultPolicy`; no network access |
| `vision` | Screenshot + state sent to an OpenAI-compatible model |
| `manual` | No agent task; input comes from the user |

The mode is first in the UI ("Default" is the first option) and is the fallback
for unknown or missing values. `Repository.effective_ai(game_id)` starts from
the global AI settings and applies non-empty per-game overrides.

## Vision agent

### Observation

Each turn receives:

- the current 160×144 PNG as a data URL;
- a compact JSON state (location, coordinates, badges, money, playtime, battle,
  Pokédex counts, party species/level/HP/status/moves);
- a human-readable state summary;
- the delta since the previous state;
- the result of the previous action;
- the active plan;
- optionally, recent previous screenshots (bounded by `AI_IMAGE_HISTORY`) and
  the rolling turn history.

The system prompt defines the eight buttons, how long to hold them, and the
exact JSON output schema.

### Decision format

```json
{
  "thought": "Standing at the north exit of Pallet Town; the path is clear.",
  "plan": ["Walk north to Route 1", "Cross the grass", "Reach Viridian City"],
  "actions": [
    {"buttons": ["up"], "frames": 24},
    {"buttons": ["a"], "frames": 4}
  ],
  "memory": "Oak's lab is south of here.",
  "done": false
}
```

The parser is intentionally tolerant. It accepts fenced JSON, leading prose,
single-action objects, `action`/`buttons`/`press`/`sequence` keys, `hold` as an
alias for `frames`, button aliases (`enter` → `start`, arrows, `north`), and
`{"up": 12}`-style maps. Actions are clamped to `max_actions` and `max_frames`.
Invalid output raises `ParseError`, which is surfaced to the dashboard.

### Memory

`RollingMemory` is a `deque` capped at `AI_MAX_CONTEXT_TURNS`. Each turn stores
the observed state, delta, thought, plan, actions, result, optional screenshot,
and error. `build_messages()` emits a system prompt, then alternating
observation/decision pairs for recent turns, then the current observation.
Only the most recent `AI_IMAGE_HISTORY` screenshots are reattached; older turns
are represented as text to control token use.

### Client

`VisionClient` uses `httpx.AsyncClient` and POSTs to
`{base_url}/chat/completions`, inserting `/v1` when absent. It retries network
errors and HTTP 429/5xx once. `test_connection()` calls `{base}/models` and
returns the first 50 model IDs. No vendor SDK is used.

## WebSocket protocol

Endpoint: `GET /ws/games/{game_id}` (WebSocket upgrade).

On connect the server sends:

```json
{"type": "hello", "game": {...}, "state": {...}, "agent": {...},
 "memory": [...], "events": [...], "ai": {...}}
{"type": "frame", "seq": 12, "data": "<base64 PNG>"}
```

Then, at most every 50 ms, it compares monotonically increasing revisions:

| Message | Trigger | Payload |
| --- | --- | --- |
| `frame` | new captured frame | `seq`, `data` (base64 PNG) |
| `state` | state snapshot changed | `state` |
| `agent` | agent status/thought/plan changed | `agent` |
| `memory` | turn added/cleared | `memory` |
| `events` | event appended | last 40 `events` |
| `ping` | every 15 s | `time` |

The browser keeps only the newest decoded frame (`Image.onload` order guard)
and draws it in `requestAnimationFrame`. Frames are 160×144 RGB PNGs, base64
encoded. `POKESIM_FRAME_FPS` caps capture; the worker may tick faster.

If the game is unknown, the server sends `{"type":"error"}` and closes with
4404. Unexpected errors close with 1011.

## Persistence and files

```
data/
  settings.json          # global AI config incl. api_key (mode 0600)
  games.json             # per-game profiles, modes, overrides
  games/<game-id>/       # PyBoy ROM copy and .ram save
  roms/<zip-slug>/       # ROMs extracted from .zip archives
```

`Repository._write()` writes JSON to a temporary file in the same directory,
flushes and fsyncs it, then uses `os.replace`. Readers fall back to defaults on
missing or corrupt files. The data directory must be writable; mounted ROMs do
not need to be.

ROM discovery is recursive for `.gb`/`.gbc`. For each `.zip`, the first ROM
member is extracted to `data/roms/<slug>/`. Profiles are keyed by a slug of the
title plus a short SHA-1 fingerprint, so moving or renaming a ROM creates a new
profile while replacing it in place keeps the existing one.

PyBoy expects `.ram` next to the ROM. The app copies the ROM into the writable
game directory, copies a matching `.ram`/`.sav` if present, and starts PyBoy on
the copy. This keeps read-only ROM mounts working.

## Security

The dashboard is an admin surface with no authentication. It controls a local
emulator and can display API-backed game state; anyone who can reach the port
can use it. Defaults bind to `127.0.0.1` locally and publish only loopback in
Compose. Put it behind an authenticated reverse proxy before exposing it.

"""FastAPI application: REST control plane plus a read-only WebSocket stream."""

from __future__ import annotations

import asyncio
import importlib.util
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import __version__
from .agent.client import AIClientError, VisionClient
from .config import Settings, load_settings
from .manager import GameManager
from .models import (
    AISettingsPatch,
    ConnectionTestRequest,
    ControlRequest,
    GameSettingsPatch,
    InputRequest,
)
from .session import AI_MODES, SessionError
from .store import Repository

log = logging.getLogger(__name__)
STATIC = Path(__file__).parent / "static"


def _error_detail(exc: Exception) -> str:
    return str(exc) or exc.__class__.__name__


def create_app(settings: Settings | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        cfg = settings or load_settings()
        cfg.ensure_dirs()
        logging.basicConfig(
            level=getattr(logging, cfg.log_level.upper(), logging.INFO),
            format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        )
        repository = Repository(cfg)
        manager = GameManager(cfg, repository)
        app.state.settings = cfg
        app.state.repository = repository
        app.state.manager = manager
        log.info("PokeSim Agent ready with %d game(s)", len(manager.sessions))
        try:
            yield
        finally:
            await manager.shutdown()

    app = FastAPI(
        title="PokeSim Agent",
        version=__version__,
        description="An OpenAI-compatible vision agent for PokeSim.",
        lifespan=lifespan,
    )

    # These accessors must not be called ``manager``/``repository``: the
    # lifespan closure above holds the actual instances in local variables with
    # those names, and a nested ``def manager`` would shadow them at runtime.
    def get_manager() -> GameManager:
        instance = getattr(app.state, "manager", None)
        if instance is None:
            raise HTTPException(status_code=503, detail="Application is still starting")
        return instance

    def get_repository() -> Repository:
        instance = getattr(app.state, "repository", None)
        if instance is None:
            raise HTTPException(status_code=503, detail="Application is still starting")
        return instance

    # ---------------- pages ----------------
    @app.get("/", include_in_schema=False)
    async def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/favicon.svg", include_in_schema=False)
    async def favicon():
        return FileResponse(STATIC / "favicon.svg")

    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    # ---------------- health / games ----------------
    @app.get("/api/health")
    async def health():
        return {
            "ok": True,
            "version": __version__,
            "time": time.time(),
            "pyboy": importlib.util.find_spec("pyboy") is not None,
            "games": len(get_manager().sessions),
        }

    @app.get("/api/games")
    async def list_games():
        return {
            "games": get_manager().list_games(),
            "ai": get_repository().get_ai().public(),
            "modes": list(AI_MODES),
        }

    @app.get("/api/games/{game_id}")
    async def get_game(game_id: str):
        try:
            return get_manager().get(game_id).snapshot()
        except SessionError as exc:
            raise HTTPException(status_code=404, detail=_error_detail(exc)) from exc

    @app.post("/api/games/{game_id}/start")
    async def start_game(game_id: str):
        try:
            return await get_manager().start(game_id)
        except SessionError as exc:
            raise HTTPException(status_code=400, detail=_error_detail(exc)) from exc

    @app.post("/api/games/{game_id}/stop")
    async def stop_game(game_id: str):
        try:
            return await get_manager().stop(game_id)
        except SessionError as exc:
            raise HTTPException(status_code=404, detail=_error_detail(exc)) from exc

    @app.post("/api/games/{game_id}/control")
    async def control_game(game_id: str, request: ControlRequest):
        try:
            session = get_manager().get(game_id)
            if request.action == "take_control":
                return await session.take_control()
            if request.action == "handover":
                return await session.handover()
            if request.action == "pause":
                return await session.pause()
            return await session.resume()
        except SessionError as exc:
            raise HTTPException(status_code=400, detail=_error_detail(exc)) from exc

    @app.patch("/api/games/{game_id}")
    async def patch_game(game_id: str, request: GameSettingsPatch):
        try:
            session = get_manager().get(game_id)
            updates: dict = {}
            if request.name is not None:
                updates["name"] = request.name
            if request.ai_mode is not None:
                updates["ai_mode"] = request.ai_mode
            overrides = request.overrides()
            if overrides:
                updates["overrides"] = overrides
            if request.clear_overrides:
                updates["clear_overrides"] = True
            await session.update_settings(updates)
            return session.summary()
        except SessionError as exc:
            raise HTTPException(status_code=400, detail=_error_detail(exc)) from exc

    @app.post("/api/games/{game_id}/input")
    async def input_game(game_id: str, request: InputRequest):
        try:
            return await get_manager().get(game_id).press(
                request.button, request.action, request.frames
            )
        except SessionError as exc:
            raise HTTPException(status_code=409, detail=_error_detail(exc)) from exc

    @app.post("/api/games/{game_id}/agent/reset")
    async def reset_agent(game_id: str):
        try:
            session = get_manager().get(game_id)
            session.memory.clear()
            session.set_agent(thought="", plan=[], last_action="", turn=0, error=None)
            session.log_event("agent", "Agent memory cleared")
            return session.summary()
        except SessionError as exc:
            raise HTTPException(status_code=404, detail=_error_detail(exc)) from exc

    @app.get("/api/games/{game_id}/events")
    async def game_events(game_id: str):
        try:
            return {"events": get_manager().get(game_id).events_snapshot()}
        except SessionError as exc:
            raise HTTPException(status_code=404, detail=_error_detail(exc)) from exc

    @app.post("/api/roms/refresh")
    async def refresh_roms():
        return {"games": get_manager().refresh()}

    # ---------------- settings ----------------
    @app.get("/api/settings")
    async def get_settings():
        return get_repository().get_ai().public()

    @app.put("/api/settings")
    async def put_settings(request: AISettingsPatch):
        updates = request.to_updates()
        config = get_repository().update_ai(updates)
        # A running agent may be sleeping in an error backoff; restart it so the
        # new endpoint is used immediately.
        for session in get_manager().sessions.values():
            if session.running:
                try:
                    await session.restart_agent()
                except Exception:
                    log.exception("Could not restart agent for %s", session.game_id)
        return config.public()

    @app.post("/api/settings/test")
    async def test_settings(request: ConnectionTestRequest):
        config = get_repository().get_ai()
        overrides = {
            "base_url": request.base_url,
            "api_key": request.api_key,
            "model": request.model,
        }
        config = config.with_overrides(
            {key: value for key, value in overrides.items() if value is not None}
        )
        try:
            result = await VisionClient(config).test_connection()
            return {**result, "model": config.model}
        except AIClientError as exc:
            raise HTTPException(status_code=400, detail=_error_detail(exc)) from exc

    # ---------------- WebSocket ----------------
    @app.websocket("/ws/games/{game_id}")
    async def game_socket(websocket: WebSocket, game_id: str):
        await websocket.accept()
        try:
            session = get_manager().get(game_id)
        except SessionError as exc:
            await websocket.send_json({"type": "error", "message": _error_detail(exc)})
            await websocket.close(code=4404)
            return
        loop = asyncio.get_running_loop()
        last_frame = -1
        last_state = -1
        last_agent = -1
        last_memory = -1
        last_events = -1
        last_ping = loop.time()
        try:
            snapshot = session.snapshot()
            await websocket.send_json(
                {
                    "type": "hello",
                    "game": session.summary(),
                    "state": snapshot.get("state"),
                    "agent": snapshot.get("agent"),
                    "memory": snapshot.get("memory"),
                    "events": snapshot.get("events"),
                    "ai": snapshot.get("ai"),
                }
            )
            if snapshot.get("frame"):
                await websocket.send_json(
                    {
                        "type": "frame",
                        "seq": snapshot.get("frame_seq"),
                        "data": snapshot["frame"],
                    }
                )
                last_frame = int(snapshot.get("frame_seq") or 0)
            while True:
                frame_seq = session.frame_seq
                state_rev = session.state_rev
                agent_rev = session.agent_rev
                memory_rev = session.memory.revision
                events_rev = session.events_rev
                if frame_seq != last_frame and session.frame_b64:
                    last_frame = frame_seq
                    await websocket.send_json(
                        {
                            "type": "frame",
                            "seq": frame_seq,
                            "data": session.frame_b64,
                        }
                    )
                if state_rev != last_state:
                    last_state = state_rev
                    await websocket.send_json(
                        {"type": "state", "state": session.current_state()}
                    )
                if agent_rev != last_agent:
                    last_agent = agent_rev
                    await websocket.send_json(
                        {"type": "agent", "agent": session.agent_snapshot()}
                    )
                if memory_rev != last_memory:
                    last_memory = memory_rev
                    await websocket.send_json(
                        {"type": "memory", "memory": session.memory_snapshot()}
                    )
                if events_rev != last_events:
                    last_events = events_rev
                    await websocket.send_json(
                        {"type": "events", "events": session.events_snapshot()[-40:]}
                    )
                if loop.time() - last_ping > 15:
                    last_ping = loop.time()
                    await websocket.send_json({"type": "ping", "time": time.time()})
                await asyncio.sleep(0.05)
        except WebSocketDisconnect:
            return
        except (RuntimeError, asyncio.CancelledError):
            return
        except Exception:
            log.exception("WebSocket for %s failed", game_id)
            try:
                await websocket.close(code=1011)
            except Exception:
                pass

    @app.exception_handler(SessionError)
    async def session_error_handler(_, exc: SessionError):
        return JSONResponse(status_code=400, content={"detail": _error_detail(exc)})

    return app


app = create_app()

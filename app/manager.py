"""Discovers ROMs, registers per-game profiles, and owns live sessions."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import time
import zipfile
from pathlib import Path

from .config import Settings
from .emulator import read_rom_title
from .session import GameSession, SessionError
from .store import Repository

log = logging.getLogger(__name__)

ROM_SUFFIXES = {".gb", ".gbc"}


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:48] or "game"


def file_fingerprint(path: Path) -> str:
    digest = hashlib.sha1()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError:
        digest.update(str(path).encode())
    return digest.hexdigest()[:10]


class GameManager:
    def __init__(self, settings: Settings, repository: Repository):
        self.settings = settings
        self.repository = repository
        self.sessions: dict[str, GameSession] = {}
        self._lock = asyncio.Lock()
        self._refresh_sync()

    # ---------------- discovery ----------------
    def _rom_files(self) -> list[Path]:
        found: list[Path] = []
        for path in sorted(self.settings.roms_dir.rglob("*")):
            if not path.is_file():
                continue
            suffix = path.suffix.lower()
            if suffix in ROM_SUFFIXES:
                found.append(path)
            elif suffix == ".zip":
                extracted = self._extract_zip(path)
                if extracted:
                    found.append(extracted)
        return found

    def _extract_zip(self, path: Path) -> Path | None:
        target_dir = self.settings.data_dir / "roms" / slugify(path.stem)
        target_dir.mkdir(parents=True, exist_ok=True)
        try:
            with zipfile.ZipFile(path) as archive:
                members = [
                    item
                    for item in archive.infolist()
                    if Path(item.filename).suffix.lower() in ROM_SUFFIXES
                    and not item.is_dir()
                ]
                if not members:
                    return None
                member = members[0]
                target = target_dir / Path(member.filename).name
                if not target.exists() or target.stat().st_size != member.file_size:
                    tmp = target.with_suffix(target.suffix + ".tmp")
                    with archive.open(member) as source, tmp.open("wb") as output:
                        while True:
                            chunk = source.read(1024 * 1024)
                            if not chunk:
                                break
                            output.write(chunk)
                    tmp.replace(target)
                return target
        except (OSError, zipfile.BadZipFile) as exc:
            log.warning("Could not read ROM archive %s: %s", path, exc)
            return None

    def _refresh_sync(self) -> None:
        existing = {profile["id"]: profile for profile in self.repository.list_games()}
        known_roms = {
            str(Path(profile["rom"]).resolve())
            for profile in existing.values()
            if profile.get("rom")
        }
        names = {str(profile.get("name") or "") for profile in existing.values()}
        rom_count = 0
        for rom in self._rom_files():
            rom_count += 1
            resolved = str(rom.resolve())
            profile = next(
                (
                    item
                    for item in existing.values()
                    if item.get("rom") and str(Path(item["rom"]).resolve()) == resolved
                ),
                None,
            )
            if profile is None:
                title = read_rom_title(rom)
                name = title or rom.stem
                if name in names:
                    name = f"{name} ({rom.stem[:8]})"
                names.add(name)
                game_id = f"{slugify(name)}-{file_fingerprint(rom)}"
                profile = self.repository.upsert_game(
                    {
                        "id": game_id,
                        "name": name,
                        "title": title or rom.stem,
                        "rom": resolved,
                        "demo": False,
                        "ai_mode": "default",
                        "overrides": {},
                        "created_at": time.time(),
                    }
                )
                known_roms.add(resolved)
                log.info("Discovered ROM %s as %s", rom.name, game_id)
            self._ensure_session(profile)

        # A local demo is the default experience when no ROM is mounted yet.
        if rom_count == 0 and self.settings.demo_game:
            demo = next(
                (profile for profile in existing.values() if profile.get("demo")),
                None,
            )
            if demo is None:
                demo = self.repository.upsert_game(
                    {
                        "id": "demo",
                        "name": "Pokémon Demo",
                        "title": "Pokémon Demo (no ROM)",
                        "rom": None,
                        "demo": True,
                        "ai_mode": "default",
                        "overrides": {},
                        "created_at": time.time(),
                    }
                )
            self._ensure_session(demo)

        # Profiles whose ROM was removed stay visible so the user can restore it.
        for profile in self.repository.list_games():
            self._ensure_session(profile)

    def _ensure_session(self, profile: dict) -> GameSession:
        game_id = str(profile["id"])
        session = self.sessions.get(game_id)
        if session is None:
            session = GameSession(profile, self.settings, self.repository)
            self.sessions[game_id] = session
        return session

    def refresh(self) -> list[dict]:
        """Rescan ROMs and add sessions for newly found games."""
        self._refresh_sync()
        return self.list_games()

    # ---------------- access ----------------
    def list_games(self) -> list[dict]:
        return sorted(
            (session.summary() for session in self.sessions.values()),
            key=lambda item: (bool(item.get("demo")), (item.get("name") or "").lower()),
        )

    def get(self, game_id: str) -> GameSession:
        session = self.sessions.get(game_id)
        if session is None:
            raise SessionError(f"Unknown game: {game_id}")
        return session

    async def start(self, game_id: str) -> dict:
        async with self._lock:
            return await self.get(game_id).start()

    async def stop(self, game_id: str) -> dict:
        async with self._lock:
            return await self.get(game_id).stop()

    async def shutdown(self) -> None:
        for session in list(self.sessions.values()):
            if session.running:
                try:
                    await session.stop()
                except Exception:
                    log.exception("Could not stop %s cleanly", session.game_id)

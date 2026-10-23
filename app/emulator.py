"""Emulator backends: PyBoy for real ROMs, a self-contained demo for no-ROM use."""

from __future__ import annotations

import logging
import random
import shutil
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from .gen1 import Gen1Reader, summary

log = logging.getLogger(__name__)

BUTTONS = ("up", "down", "left", "right", "a", "b", "start", "select")
TITLE_ADDRESS = 0x134
TITLE_LENGTH = 16


class EmulatorError(RuntimeError):
    pass


def read_rom_title(path: Path) -> str:
    try:
        with path.open("rb") as handle:
            header = handle.read(0x150)
        raw = header[TITLE_ADDRESS : TITLE_ADDRESS + TITLE_LENGTH]
        title = raw.split(b"\x00", 1)[0].decode("ascii", "ignore").strip()
        return title or path.stem
    except OSError:
        return path.stem


def _font(size: int = 10):
    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # Pillow < 10
        return ImageFont.load_default()


class BaseEmulator:
    kind = "base"

    def __init__(self, title: str = "Pokémon"):
        self.title = title
        self.frames = 0

    def tick(self, frames: int = 1) -> None:  # pragma: no cover - abstract
        raise NotImplementedError

    def button_down(self, button: str) -> None:  # pragma: no cover - abstract
        raise NotImplementedError

    def button_up(self, button: str) -> None:  # pragma: no cover - abstract
        raise NotImplementedError

    def press(self, button: str, frames: int = 4) -> None:
        self.button_down(button)
        try:
            self.tick(max(1, frames))
        finally:
            self.button_up(button)

    def screen(self) -> Image.Image:  # pragma: no cover - abstract
        raise NotImplementedError

    def snapshot(self) -> dict[str, Any]:  # pragma: no cover - abstract
        raise NotImplementedError

    def close(self) -> None:
        pass


class MockEmulator(BaseEmulator):
    """A tiny procedural game used when no ROM/PyBoy is available.

    It is deliberately obvious that this is a demo, but it still responds to all
    eight buttons so the controller, agent loop, canvas and WebSocket can be
    exercised end-to-end without copyrighted ROMs.
    """

    kind = "demo"

    def __init__(self, title: str = "Pokémon Demo"):
        super().__init__(title)
        self.map_id = 0
        self.x = 5
        self.y = 6
        self.money = 3000
        self.badges = [False] * 8
        self.message = "A wild demo appears!"
        self.message_frames = 90
        self.held: set[str] = set()
        self.party = [
            {
                "slot": 1,
                "species_id": 153,
                "species": "Bulbasaur",
                "level": 5,
                "hp": 19,
                "max_hp": 19,
                "status": "OK",
                "attack": 9,
                "defense": 9,
                "speed": 9,
                "special": 10,
                "moves": [33, 45, 0, 0],
                "pp": [35, 40, 0, 0],
            }
        ]
        self.map_name = "Pallet Town"
        self.in_battle = 0
        self.steps = 0
        self.seed = 7

    def tick(self, frames: int = 1) -> None:
        for _ in range(max(1, frames)):
            self.frames += 1
            if self.message_frames > 0:
                self.message_frames -= 1
            if "up" in self.held:
                self._move(0, -1)
            elif "down" in self.held:
                self._move(0, 1)
            elif "left" in self.held:
                self._move(-1, 0)
            elif "right" in self.held:
                self._move(1, 0)

    def _move(self, dx: int, dy: int) -> None:
        if self.frames % 8:
            return
        self.x = max(0, min(19, self.x + dx))
        self.y = max(0, min(17, self.y + dy))
        self.steps += 1
        if self.steps and self.steps % 120 == 0:
            self.money = min(999999, self.money + 120)
            self.message = "Found a few coins on the ground."
            self.message_frames = 100

    def button_down(self, button: str) -> None:
        if button not in BUTTONS:
            return
        self.held.add(button)
        if button == "a":
            self.message = random.Random(self.frames).choice(
                [
                    "Oak: Take your time — this is a demo.",
                    "The tall grass rustles suspiciously.",
                    "A sign reads: ROUTE 1, PALLET TOWN.",
                    "Bulbasaur looks ready to go!",
                ]
            )
            self.message_frames = 120
            if self.frames % 13 == 0:
                self.money = min(999999, self.money + 10)
        elif button == "b":
            self.message = "You put the demo away."
            self.message_frames = 60
        elif button == "start":
            self.message = "MENU — POKéDEX  POKéMON  ITEM  EXIT"
            self.message_frames = 80
        elif button == "select":
            self.message = "Demo state: all systems nominal."
            self.message_frames = 80

    def button_up(self, button: str) -> None:
        self.held.discard(button)

    def press(self, button: str, frames: int = 4) -> None:
        self.button_down(button)
        try:
            self.tick(max(1, frames))
        finally:
            self.button_up(button)

    def screen(self) -> Image.Image:
        image = Image.new("RGB", (160, 144), (216, 232, 200))
        draw = ImageDraw.Draw(image)
        # Sky / ground split with a few tiles.
        draw.rectangle((0, 0, 159, 24), fill=(200, 220, 184))
        draw.rectangle((0, 24, 159, 144), fill=(184, 208, 168))
        for tile_x in range(0, 160, 16):
            for tile_y in range(32, 136, 16):
                shade = (172, 196, 156) if (tile_x // 16 + tile_y // 16) % 2 else (184, 208, 168)
                draw.rectangle((tile_x, tile_y, tile_x + 15, tile_y + 15), fill=shade)
        # A couple of buildings.
        draw.rectangle((8, 32, 44, 64), fill=(112, 128, 104), outline=(48, 64, 48))
        draw.rectangle((14, 44, 24, 64), fill=(48, 64, 48))
        draw.rectangle((118, 80, 152, 112), fill=(120, 136, 112), outline=(48, 64, 48))
        draw.rectangle((126, 92, 136, 112), fill=(48, 64, 48))
        # Player sprite.
        px, py = 24 + self.x * 5, 40 + self.y * 4
        draw.rectangle((px, py, px + 7, py + 10), fill=(232, 88, 72), outline=(32, 32, 32))
        draw.rectangle((px + 2, py - 4, px + 5, py + 1), fill=(240, 208, 160), outline=(32, 32, 32))
        # HUD.
        draw.rectangle((0, 0, 159, 22), fill=(248, 248, 240), outline=(48, 64, 48))
        draw.text((4, 2), self.title.upper()[:19], fill=(32, 40, 32), font=_font(7))
        draw.text(
            (4, 11),
            f"{self.map_name.upper()}  {self.x},{self.y}  BADGES {sum(self.badges)}/8",
            fill=(48, 64, 48),
            font=_font(6),
        )
        draw.text((116, 2), "DEMO", fill=(184, 72, 56), font=_font(7))
        # Dialogue / status box.
        draw.rectangle((4, 112, 155, 140), fill=(248, 248, 240), outline=(32, 40, 32))
        line = self.message if self.message_frames > 0 else "The demo keeps playing while you watch."
        draw.text((9, 118), line[:52], fill=(32, 40, 32), font=_font(7))
        if self.message_frames > 0:
            draw.text((140, 128), "▼", fill=(32, 40, 32), font=_font(8))
        # Party pips.
        for index, mon in enumerate(self.party):
            draw.rectangle((6 + index * 18, 102, 20 + index * 18, 109), fill=(112, 184, 120))
            draw.text((8 + index * 18, 101), f"{mon['hp']}", fill=(24, 56, 24), font=_font(6))
        return image

    def snapshot(self) -> dict[str, Any]:
        party = [dict(mon) for mon in self.party]
        party[0]["hp"] = max(
            0, min(party[0]["max_hp"], party[0]["hp"] - (1 if self.frames % 900 == 0 else 0))
        )
        return {
            "game": self.title,
            "trainer": "ASH",
            "rival": "GARY",
            "map_id": self.map_id,
            "map_name": self.map_name,
            "x": self.x,
            "y": self.y,
            "badges": list(self.badges),
            "badge_count": sum(self.badges),
            "badge_names": [name for name, earned in zip(
                ("Boulder", "Cascade", "Thunder", "Rainbow", "Soul", "Marsh", "Volcano", "Earth"),
                self.badges,
            ) if earned],
            "money": self.money,
            "playtime": f"{self.frames // 216000:02d}:{(self.frames // 3600) % 60:02d}:{(self.frames // 60) % 60:02d}",
            "in_battle": self.in_battle,
            "battle": "overworld",
            "pokedex_owned": 1,
            "pokedex_seen": 3,
            "party": party,
            "party_count": len(party),
            "timestamp": __import__("time").time(),
            "demo": True,
        }

    def summary(self) -> str:
        return summary(self.snapshot())


class PyBoyEmulator(BaseEmulator):
    """Real Game Boy emulation through PyBoy in headless mode."""

    kind = "pyboy"

    def __init__(self, rom_path: Path, save_dir: Path, *, title: str | None = None, speed: int = 0):
        super().__init__(title or read_rom_title(rom_path))
        try:
            from pyboy import PyBoy
        except Exception as exc:  # pragma: no cover - depends on environment
            raise EmulatorError(
                "PyBoy is not installed. Run the Docker image or `pip install pyboy`."
            ) from exc
        if not rom_path.exists():
            raise EmulatorError(f"ROM not found: {rom_path}")
        save_dir.mkdir(parents=True, exist_ok=True)
        suffix = rom_path.suffix.lower() if rom_path.suffix else ".gb"
        local_rom = save_dir / f"game{suffix}"
        if not local_rom.exists() or local_rom.stat().st_size != rom_path.stat().st_size:
            shutil.copy2(rom_path, local_rom)
        # PyBoy looks for a .ram next to the ROM; keep the upstream file too.
        for candidate in (rom_path.with_suffix(rom_path.suffix + ".ram"), rom_path.with_suffix(".ram"), rom_path.with_suffix(".sav")):
            target = local_rom.with_suffix(local_rom.suffix + ".ram")
            if candidate.exists() and not target.exists():
                try:
                    shutil.copy2(candidate, target)
                except OSError:
                    pass
                break
        try:
            try:
                self.pyboy = PyBoy(
                    str(local_rom),
                    window="null",
                    sound_emulated=False,
                )
            except TypeError:
                # Older PyBoy releases do not accept ``sound_emulated``.
                self.pyboy = PyBoy(str(local_rom), window="null")
        except Exception as exc:  # pragma: no cover - hardware/environment specific
            raise EmulatorError(f"PyBoy could not start: {exc}") from exc
        try:
            self.pyboy.set_emulation_speed(speed)
        except Exception:
            pass
        self.rom_path = rom_path
        self.local_rom = local_rom
        self.reader = Gen1Reader(lambda address: self.pyboy.memory[address], game_title=self.title)
        self._closed = False
        log.info("PyBoy started with %s", local_rom)

    def tick(self, frames: int = 1) -> None:
        frames = max(1, frames)
        try:
            self.pyboy.tick(frames, True)
        except TypeError:  # older PyBoy signature
            for _ in range(frames):
                self.pyboy.tick()
        self.frames += frames

    def button_down(self, button: str) -> None:
        if button in BUTTONS:
            try:
                self.pyboy.button_press(button)
            except Exception:
                pass

    def button_up(self, button: str) -> None:
        if button in BUTTONS:
            try:
                self.pyboy.button_release(button)
            except Exception:
                pass

    def press(self, button: str, frames: int = 4) -> None:
        self.button_down(button)
        try:
            self.tick(max(1, frames))
        finally:
            self.button_up(button)

    def screen(self) -> Image.Image:
        try:
            image = self.pyboy.screen.image
            if isinstance(image, Image.Image):
                return image.convert("RGB")
        except Exception:
            pass
        return Image.new("RGB", (160, 144), (16, 24, 16))

    def snapshot(self) -> dict[str, Any]:
        state = self.reader.snapshot()
        state["demo"] = False
        return state

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            self.pyboy.stop(save=True)
        except Exception:
            log.exception("PyBoy did not shut down cleanly")

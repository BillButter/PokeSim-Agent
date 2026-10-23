"""Generation I game-state decoding.

The addresses below are the well-known Pokémon Red/Blue/Yellow WRAM addresses
used by PyBoy and the pret/pokered disassembly.  Every read is defensive: a
partially booted ROM, an unsupported generation, or a damaged save should
produce a useful partial snapshot rather than taking the dashboard down.
"""

from __future__ import annotations

import time
from typing import Any, Callable

from .gen1_data import MAP_NAMES, SPECIES_BY_INDEX

PLAYER_NAME = 0xD158
RIVAL_NAME = 0xD34A
PARTY_COUNT = 0xD163
PARTY_SPECIES = 0xD164
PARTY_MONS = 0xD16B
PARTY_STRUCT = 44
MONEY = 0xD347
BADGES = 0xD356
CUR_MAP = 0xD35E
Y_COORD = 0xD361
X_COORD = 0xD362
IN_BATTLE = 0xD057
POKEDEX_OWNED = 0xD2F7
POKEDEX_SEEN = 0xD30A
PLAY_HOURS = 0xDA40
PLAY_MAXED = 0xDA41
PLAY_MINUTES = 0xDA42
PLAY_SECONDS = 0xDA43

BADGE_NAMES = (
    "Boulder",
    "Cascade",
    "Thunder",
    "Rainbow",
    "Soul",
    "Marsh",
    "Volcano",
    "Earth",
)

# Offsets inside a 44-byte party_struct.
OFF_HP = 1
OFF_STATUS = 4
OFF_MOVES = 8
OFF_PP = 29
OFF_LEVEL = 33
OFF_MAX_HP = 34
OFF_ATTACK = 36
OFF_DEFENSE = 38
OFF_SPEED = 40
OFF_SPECIAL = 42

TEXT_CHARS: dict[int, str] = {0x7F: " "}
TEXT_CHARS.update({0x80 + i: chr(ord("A") + i) for i in range(26)})
TEXT_CHARS.update({0xA0 + i: chr(ord("a") + i) for i in range(26)})
TEXT_CHARS.update(
    {
        0x9A: "(",
        0x9B: ")",
        0x9C: ":",
        0x9D: ";",
        0x9E: "[",
        0x9F: "]",
        0xBA: "é",
        0xBB: "'d",
        0xBC: "'l",
        0xBD: "'s",
        0xBE: "'t",
        0xBF: "'v",
        0xE0: "'",
        0xE1: "PK",
        0xE2: "MN",
        0xE3: "-",
        0xE4: "'r",
        0xE5: "'m",
        0xE6: "?",
        0xE7: "!",
        0xE8: ".",
        0xEC: "▷",
        0xED: "▶",
        0xEE: "▼",
        0xEF: "♂",
        0xF0: "¥",
        0xF1: "×",
        0xF2: ".",
        0xF3: "/",
        0xF4: ",",
        0xF5: "♀",
    }
)
TEXT_CHARS.update({0xF6 + i: str(i) for i in range(10)})

STATUS_LABELS = (
    (0x07, "Asleep"),
    (0x08, "Poisoned"),
    (0x10, "Burned"),
    (0x20, "Frozen"),
    (0x40, "Paralyzed"),
)


def decode_text(data: bytes, *, limit: int = 12) -> str:
    out: list[str] = []
    for value in data[:limit]:
        if value in (0x00, 0x50):
            break
        out.append(TEXT_CHARS.get(value, ""))
    return "".join(out).strip()


def bcd_money(raw: bytes) -> int:
    digits = []
    for byte in raw[:3]:
        high, low = byte >> 4, byte & 0x0F
        if high > 9 or low > 9:
            return 0
        digits.extend((high, low))
    return int("".join(str(digit) for digit in digits)) if digits else 0


def count_bits(raw: bytes) -> int:
    return sum(byte.bit_count() for byte in raw)


def status_label(value: int) -> str:
    for bit, label in STATUS_LABELS:
        if value & bit:
            return label
    return "OK"


class Gen1Reader:
    """Reads a snapshot through a ``read(address) -> int`` callable."""

    def __init__(self, read: Callable[[int], int], *, game_title: str = "Pokémon"):
        self._read = read
        self.game_title = game_title

    def _byte(self, address: int) -> int:
        try:
            return int(self._read(address)) & 0xFF
        except Exception:
            return 0

    def _bytes(self, address: int, length: int) -> bytes:
        return bytes(self._byte(address + offset) for offset in range(length))

    def _u16(self, address: int) -> int:
        high = self._byte(address)
        low = self._byte(address + 1)
        return (high << 8) | low

    def _name(self, address: int) -> str:
        return decode_text(self._bytes(address, 11), limit=11)

    def _party(self) -> list[dict[str, Any]]:
        count = min(6, max(0, self._byte(PARTY_COUNT)))
        party: list[dict[str, Any]] = []
        for index in range(count):
            base = PARTY_MONS + index * PARTY_STRUCT
            species_id = self._byte(PARTY_SPECIES + index)
            if species_id == 0:
                species_id = self._byte(base)
            name = SPECIES_BY_INDEX.get(species_id, f"Species {species_id}")
            max_hp = self._u16(base + OFF_MAX_HP)
            hp = self._u16(base + OFF_HP)
            if max_hp == 0 and hp == 0:
                # Some saves are read while the party is being rearranged.
                max_hp = hp
            party.append(
                {
                    "slot": index + 1,
                    "species_id": species_id,
                    "species": name,
                    "level": self._byte(base + OFF_LEVEL),
                    "hp": hp,
                    "max_hp": max_hp,
                    "status": status_label(self._byte(base + OFF_STATUS)),
                    "attack": self._u16(base + OFF_ATTACK),
                    "defense": self._u16(base + OFF_DEFENSE),
                    "speed": self._u16(base + OFF_SPEED),
                    "special": self._u16(base + OFF_SPECIAL),
                    "moves": [
                        self._byte(base + OFF_MOVES + offset) for offset in range(4)
                    ],
                    "pp": [self._byte(base + OFF_PP + offset) for offset in range(4)],
                }
            )
        return party

    def snapshot(self) -> dict[str, Any]:
        try:
            badge_byte = self._byte(BADGES)
            badges = [bool(badge_byte & (1 << bit)) for bit in range(8)]
            party = self._party()
            map_id = self._byte(CUR_MAP)
            hours = self._byte(PLAY_HOURS)
            if self._byte(PLAY_MAXED):
                hours = 999
            battle = self._byte(IN_BATTLE)
            return {
                "game": self.game_title,
                "trainer": self._name(PLAYER_NAME) or "Trainer",
                "rival": self._name(RIVAL_NAME),
                "map_id": map_id,
                "map_name": MAP_NAMES.get(map_id, f"Map {map_id}"),
                "x": self._byte(X_COORD),
                "y": self._byte(Y_COORD),
                "badges": badges,
                "badge_count": sum(badges),
                "badge_names": [
                    name for name, earned in zip(BADGE_NAMES, badges) if earned
                ],
                "money": bcd_money(self._bytes(MONEY, 3)),
                "playtime": f"{hours:02d}:{self._byte(PLAY_MINUTES):02d}:{self._byte(PLAY_SECONDS):02d}",
                "in_battle": battle,
                "battle": {0: "overworld", 1: "wild", 2: "trainer"}.get(
                    battle, "unknown"
                ),
                "pokedex_owned": count_bits(self._bytes(POKEDEX_OWNED, 19)),
                "pokedex_seen": count_bits(self._bytes(POKEDEX_SEEN, 19)),
                "party": party,
                "party_count": len(party),
                "timestamp": time.time(),
            }
        except Exception as exc:  # pragma: no cover - defensive
            return {
                "game": self.game_title,
                "trainer": "Trainer",
                "map_id": 0,
                "map_name": "Unknown",
                "x": 0,
                "y": 0,
                "badges": [False] * 8,
                "badge_count": 0,
                "badge_names": [],
                "money": 0,
                "playtime": "00:00:00",
                "in_battle": 0,
                "battle": "unknown",
                "pokedex_owned": 0,
                "pokedex_seen": 0,
                "party": [],
                "party_count": 0,
                "timestamp": time.time(),
                "error": str(exc),
            }


def state_delta(previous: dict | None, current: dict | None) -> dict[str, Any]:
    """Human-readable changes between two snapshots, for the rolling memory."""
    if not previous or not current:
        return {}
    delta: dict[str, Any] = {}
    for key in ("map_name", "money", "badge_count", "pokedex_owned", "playtime"):
        if previous.get(key) != current.get(key):
            delta[key] = {"from": previous.get(key), "to": current.get(key)}
    if previous.get("party_count") != current.get("party_count"):
        delta["party_count"] = {
            "from": previous.get("party_count"),
            "to": current.get("party_count"),
        }
    before = {mon.get("slot"): mon for mon in previous.get("party", [])}
    after = {mon.get("slot"): mon for mon in current.get("party", [])}
    for slot in sorted(set(before) | set(after)):
        old, new = before.get(slot), after.get(slot)
        if not old or not new:
            continue
        label = new.get("species") or old.get("species") or f"slot {slot}"
        if old.get("hp") != new.get("hp"):
            delta[f"{label} HP"] = {"from": old.get("hp"), "to": new.get("hp")}
        if old.get("level") != new.get("level"):
            delta[f"{label} level"] = {
                "from": old.get("level"),
                "to": new.get("level"),
            }
    return delta


def summary(state: dict | None) -> str:
    """A compact one-line state summary for prompts and logs."""
    if not state:
        return "No game state yet."
    party = ", ".join(
        f"{mon.get('species')} L{mon.get('level')} {mon.get('hp')}/{mon.get('max_hp')}"
        for mon in state.get("party", [])
    ) or "no party"
    return (
        f"{state.get('trainer')} at {state.get('map_name')} "
        f"({state.get('x')},{state.get('y')}); badges {state.get('badge_count')}/8; "
        f"money ₽{state.get('money')}; party: {party}"
    )

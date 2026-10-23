from __future__ import annotations

from app import gen1
from app.gen1 import (
    BADGES,
    CUR_MAP,
    MONEY,
    PARTY_COUNT,
    PARTY_MONS,
    PARTY_SPECIES,
    PLAY_HOURS,
    PLAY_MINUTES,
    PLAY_SECONDS,
    PLAYER_NAME,
    X_COORD,
    Y_COORD,
    Gen1Reader,
    bcd_money,
    decode_text,
    state_delta,
    status_label,
)


def _encode_name(text: str) -> bytes:
    values = []
    for char in text.upper():
        if "A" <= char <= "Z":
            values.append(0x80 + ord(char) - ord("A"))
        elif char == " ":
            values.append(0x7F)
        else:
            values.append(0x00)
    return bytes(values) + b"\x50"


def test_text_and_money_helpers():
    assert decode_text(bytes([0x80, 0xA0, 0x7F, 0xE2, 0x50, 0x81])) == "Aa MN"
    assert bcd_money(bytes([0x12, 0x34, 0x56])) == 123456
    assert bcd_money(bytes([0x1A])) == 0
    assert status_label(0x00) == "OK"
    assert status_label(0x08) == "Poisoned"
    assert status_label(0x40) == "Paralyzed"


def test_reader_decodes_core_state_and_party():
    memory = bytearray(0x10000)
    memory[PLAYER_NAME : PLAYER_NAME + 4] = _encode_name("ASH")
    memory[BADGES] = 0b00000101
    memory[CUR_MAP] = 0
    memory[X_COORD] = 7
    memory[Y_COORD] = 9
    memory[MONEY : MONEY + 3] = bytes([0x00, 0x12, 0x34])
    memory[PLAY_HOURS] = 3
    memory[PLAY_MINUTES] = 4
    memory[PLAY_SECONDS] = 5

    memory[PARTY_COUNT] = 1
    memory[PARTY_SPECIES] = 153  # internal index for Bulbasaur
    base = PARTY_MONS
    memory[base + 1 : base + 3] = bytes([0x00, 19])  # hp
    memory[base + 33] = 5  # level
    memory[base + 34 : base + 36] = bytes([0x00, 19])  # max hp
    memory[base + 36 : base + 38] = bytes([0x00, 9])  # attack
    memory[base + 8 : base + 12] = bytes([33, 45, 0, 0])  # moves
    memory[base + 29 : base + 33] = bytes([35, 40, 0, 0])  # pp

    state = Gen1Reader(lambda address: memory[address], game_title="POKEMON RED").snapshot()

    assert state["game"] == "POKEMON RED"
    assert state["trainer"] == "ASH"
    assert state["map_name"] == "Pallet Town"
    assert (state["x"], state["y"]) == (7, 9)
    assert state["badge_count"] == 2
    assert state["badge_names"] == ["Boulder", "Thunder"]
    assert state["money"] == 1234
    assert state["playtime"] == "03:04:05"
    assert state["party_count"] == 1
    mon = state["party"][0]
    assert mon["species"] == "Bulbasaur"
    assert mon["level"] == 5
    assert (mon["hp"], mon["max_hp"]) == (19, 19)
    assert mon["moves"] == [33, 45, 0, 0]
    assert mon["pp"] == [35, 40, 0, 0]


def test_reader_is_defensive_when_reads_fail():
    def broken(_address):
        raise RuntimeError("not booted")

    # Individual reads are caught and treated as zero, so a not-yet-booted ROM
    # produces an empty snapshot instead of taking down the dashboard.
    state = Gen1Reader(broken).snapshot()
    assert state["trainer"] == "Trainer"
    assert state["party"] == []
    assert state["badge_count"] == 0
    assert state["map_name"] == "Pallet Town"


def test_state_delta_reports_changes():
    before = {
        "map_name": "Pallet Town",
        "money": 100,
        "badge_count": 0,
        "party_count": 1,
        "party": [{"slot": 1, "species": "Bulbasaur", "hp": 19, "level": 5}],
    }
    after = {
        "map_name": "Route 1",
        "money": 120,
        "badge_count": 1,
        "party_count": 1,
        "party": [{"slot": 1, "species": "Bulbasaur", "hp": 12, "level": 6}],
    }
    delta = state_delta(before, after)
    assert delta["map_name"] == {"from": "Pallet Town", "to": "Route 1"}
    assert delta["money"] == {"from": 100, "to": 120}
    assert delta["badge_count"] == {"from": 0, "to": 1}
    assert delta["Bulbasaur HP"] == {"from": 19, "to": 12}
    assert delta["Bulbasaur level"] == {"from": 5, "to": 6}
    assert state_delta(None, after) == {}


def test_tables_have_expected_shape():
    assert len(gen1.BADGE_NAMES) == 8
    assert "Pallet Town" in gen1.MAP_NAMES.values()

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Let the tests run from a source checkout without installing the package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import AIConfig, Settings  # noqa: E402
from app.store import Repository  # noqa: E402


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    cfg = Settings(
        host="127.0.0.1",
        port=8000,
        roms_dir=tmp_path / "roms",
        data_dir=tmp_path / "data",
        demo_game=True,
        frame_fps=60,
        emulation_speed=0,
        default_ai_mode="default",
        ai=AIConfig(
            base_url="http://localhost:11434/v1",
            api_key="",
            model="llava",
            poll_interval=0.5,
            max_context_turns=4,
            image_history=1,
            max_actions=4,
            max_frames=120,
            temperature=0.2,
            timeout=10,
        ),
    )
    cfg.ensure_dirs()
    return cfg


@pytest.fixture
def repository(settings: Settings) -> Repository:
    return Repository(settings)

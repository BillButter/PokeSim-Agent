# Third-party notices

PokeSim Agent is an unofficial fan project. It is not affiliated with or
endorsed by Nintendo, Creatures Inc., GAME FREAK inc., or The Pokémon Company.
Pokémon and related names are trademarks of their respective owners.

This repository contains **no ROMs, saves, sprites, or extracted game artwork**.
Users are responsible for supplying ROMs they are legally entitled to use and
for any redistribution of generated or extracted content.

## PokeSim

This project is a fork of [PokeSim](https://github.com/afk-sapien/PokeSim),
Copyright (c) 2026 AFK Sapien, licensed under the MIT License. The original
license text is retained in [LICENSE](LICENSE).

The fork reimplements the runtime around FastAPI and PyBoy and adds the vision
agent. No bundled PokeSim ROM datasets or sprite packs are included.

## PyBoy

Real-ROM emulation uses [PyBoy](https://github.com/Baekalfen/PyBoy), an
optional dependency installed from PyPI through the `emulator` extra or the
Docker image. PyBoy is distributed under the GNU Lesser General Public License
version 3 (LGPL-3.0); the upstream project and license text are available at
the link above. PyBoy is used as a dynamically imported Python package and can
be replaced with a compatible modified build. The Docker build does not vendor
or modify PyBoy source.

## Generation I reference data

`app/gen1_data.py` contains species-index names and map names derived from the
[pret/pokered](https://github.com/pret/pokered) disassembly project. The tables
are used only to label values read from a user-supplied ROM. See the pret
project for its license and attribution terms.

## Python dependencies

Runtime dependencies are declared in `pyproject.toml`: FastAPI, Starlette,
Uvicorn, HTTPX, Pillow, Pydantic, and python-dotenv. Each retains its own
license; installed package metadata and notices are available in the Python
environment or container image. Development-only dependencies include pytest
and pytest-asyncio.

## Fonts and assets

The dashboard uses system fonts and an inline SVG favicon. It bundles no
Pokémon artwork. The demo emulator draws a procedural placeholder scene.

# Podman Quadlet deployment

[`pokesim-agent.container`](pokesim-agent.container) runs the published image
`ghcr.io/billbutter/pokesim-agent:latest` as a systemd service and opts into
**registry-based auto-updates** with `AutoUpdate=registry`.

Podman's `podman-auto-update.timer` periodically compares the local `:latest`
image digest with the registry. When a new image is published by the
[GitHub Actions workflow](../.github/workflows/docker-publish.yml), the timer
pulls it and restarts `pokesim-agent.service`.

## Requirements

- Podman 5.0 or newer (Quadlet, healthcheck keys, `AutoUpdate=registry`)
- systemd with cgroup v2
- The image is currently published for `linux/amd64` only

## Rootless install (recommended)

The unit runs as your login user, so no root or docker group is needed.

```bash
# 1. Runtime directories
mkdir -p ~/pokesim/roms ~/pokesim/data
mkdir -p ~/.config/containers/systemd

# 2. Install the unit
cp deploy/pokesim-agent.container ~/.config/containers/systemd/

# 3. Regenerate and start
systemctl --user daemon-reload
systemctl --user start pokesim-agent.service

# 4. Start the auto-update timer
systemctl --user enable --now podman-auto-update.timer

# 5. Keep the service (and timer) running while logged out
loginctl enable-linger "$USER"
```

Open <http://127.0.0.1:8000>. Drop `.gb`, `.gbc` or `.zip` files into
`~/pokesim/roms` and restart the service. Every supported cartridge in the
read-only mount is imported into the Adventure Library at startup.

`UserNS=keep-id:uid=1000,gid=1000` maps your host account onto the image's
`pokesim` user (UID/GID 1000), so `~/pokesim/data` remains writable even if your
host UID is not 1000.

The unit sets `PUBLIC_URL=http://127.0.0.1:8000` because PokeSim rejects requests
whose `Host` header differs from that address. If you change `PublishPort` or
put the library behind a reverse proxy, change `PUBLIC_URL` to the exact
browser-visible address too.

## Auto-update

The unit contains:

```ini
Image=ghcr.io/billbutter/pokesim-agent:latest
AutoUpdate=registry
```

Quadlet turns this into the container label
`io.containers.autoupdate=registry`. The timer unit then runs
`podman auto-update`, which:

1. resolves the current digest of `ghcr.io/billbutter/pokesim-agent:latest`,
2. pulls it when it differs from the running image,
3. restarts `pokesim-agent.service`.

Check the timer and the units it watches:

```bash
systemctl --user list-timers podman-auto-update.timer
podman auto-update --dry-run
```

Force an update check immediately:

```bash
podman auto-update
```

If you prefer manual upgrades, either disable the timer
(`systemctl --user disable --now podman-auto-update.timer`) or pin a version:

```ini
Image=ghcr.io/billbutter/pokesim-agent:v0.5.3-agent
```

Auto-update still works with a version tag; it simply tracks that tag instead of
`:latest`.

## AI settings

Keep secrets out of the unit. Add a drop-in:

```bash
mkdir -p ~/.config/containers/systemd/pokesim-agent.container.d
cat > ~/.config/containers/systemd/pokesim-agent.container.d/10-ai.conf <<'EOF'
[Container]
Environment=AI_BASE_URL=https://api.example.com/v1
Environment=AI_MODEL=your-vision-model
Environment=AI_API_KEY=sk-...
EOF

systemctl --user daemon-reload
systemctl --user restart pokesim-agent.service
```

The endpoint is server-wide. The per-game **AI player** is selected in the
Adventure Library when creating an adventure and can be changed later in
**Adventure settings**:

- **Default** runs upstream PokeSim's original strategic autopilot.
- **Vision agent** sends screenshots and game state to the configured endpoint.
- **Manual only** leaves the game to the keyboard and controller.

The choice is stored with the adventure under `~/pokesim/data` and applies live.

## Rootful install

Use this only if you need a system-wide service. Copy the unit to
`/etc/containers/systemd/`, remove the `UserNS=keep-id...` line, and use
absolute paths outside your home directory:

```ini
Volume=/srv/pokesim/roms:/roms:ro,Z
Volume=/srv/pokesim/data:/data:Z
```

The container still runs as UID/GID 1000, so make the bind mounts writable for
that user:

```bash
sudo mkdir -p /srv/pokesim/{roms,data}
sudo chown -R 1000:1000 /srv/pokesim
sudo cp deploy/pokesim-agent.container /etc/containers/systemd/
sudo sed -i -e '/^UserNS=/d' -e 's#%h/pokesim#/srv/pokesim#g' \
  /etc/containers/systemd/pokesim-agent.container
sudo systemctl daemon-reload
sudo systemctl start pokesim-agent.service
sudo systemctl enable --now podman-auto-update.timer
```

The `sed` removes the rootless-only `UserNS=` key and rewrites the bind
mounts to `/srv/pokesim`. Adjust the paths if you use another location.

## Operations

```bash
systemctl --user status pokesim-agent.service
journalctl --user -u pokesim-agent.service -f
podman logs -f systemd-pokesim-agent
podman exec systemd-pokesim-agent id     # uid=1000(pokesim)
systemctl --user restart pokesim-agent.service
systemctl --user stop pokesim-agent.service
```

If the generated service is missing after `daemon-reload`, validate the unit:

```bash
/usr/lib/systemd/system-generators/podman-system-generator --user --dryrun
# or
systemd-analyze --user --generators=true verify pokesim-agent.service
```

## Auto-update and running games

An update restarts the container, which interrupts the current game session.
PyBoy saves live under `~/pokesim/data`, so progress is preserved, but the
dashboard reconnects after the restart. If you want uninterrupted play, pin a
version tag (for example `:v0.1.0`) or disable the timer until you are ready to
update.

The dashboard has no authentication and the unit publishes on `127.0.0.1` only.
Change `PublishPort=` deliberately if you expose it to a network.

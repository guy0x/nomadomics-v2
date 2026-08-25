# RUNBOOK — Strapi service + content engine (Nomadomics v2)

## Strapi runs as a persistent launchd service

Strapi is loaded as a macOS LaunchAgent so it auto-starts on boot and
auto-restarts if it crashes. No need to manually `npm run dev` anymore.

| Command | Action |
|---|---|
| `launchctl list \| grep nomadomics` | Is the service loaded? (PID + exit code) |
| `open http://localhost:1337/admin` | Open the admin panel |
| `launchctl unload ~/Library/LaunchAgents/com.nomadomics.strapi.plist` | Stop the service |
| `launchctl load ~/Library/LaunchAgents/com.nomadomics.strapi.plist` | Start the service |
| `tail -f ~/nomadomics-v2/logs/strapi-service.log` | Watch logs |
| `tail -f ~/nomadomics-v2/logs/strapi-service.err` | Watch errors |
| `curl -s -o /dev/null -w "%{http_code}" http://localhost:1337/admin` | Health check (expect 200) |

Config: `~/Library/LaunchAgents/com.nomadomics.strapi.plist`
Logs: `~/nomadomics-v2/logs/strapi-{service.log,service.err}`

## Content engine CLI

Engine venv: `~/nomadomics-v2/.venv` (Python 3.11). All commands from
`~/nomadomics-v2`. Use `env -u PYTHONPATH` first (a global PYTHONPATH leaks the
Hermes venv's site-packages and breaks engine imports).

```
env -u PYTHONPATH .venv/bin/python -m engine.cli info        # config (redacted)
env -u PYTHONPATH .venv/bin/python -m engine.cli next        # next pending topic
env -u PYTHONPATH .venv/bin/python -m engine.cli draft-one <slug>
env -u PYTHONPATH .venv/bin/python -m engine.cli run-batch [N]
env -u PYTHONPATH .venv/bin/python -m engine.cli drafts      # drafts in Strapi
```

Run tests:
```
cd ~/nomadomics-v2/engine && env -u PYTHONPATH ../.venv/bin/python -m pytest tests/ -q
```

## Kill switch (<60s)

- `launchctl unload ~/Library/LaunchAgents/com.nomadomics.strapi.plist` — halts Strapi.
- To quarantine a bad article: set `status` back to `draft` via Strapi admin or API
  (the engine token has `update` but NOT `delete` — by design, quarantine not destroy).
- Models are free-only (`:free`) until Guy flips `PREMIUM_MODEL_ENABLED` in `.env`.

## Cloudflare Tunnel — stable public API (strapi.nomadomics.blog)

Named tunnel `nomadomics-strapi` (id a7e47a22-0622-4c9d-9f99-0c1d8fbdab2a) exposes
local Strapi at https://strapi.nomadomics.blog. Runs as LaunchAgent
`com.nomadomics.cloudflared` (RunAtLoad + KeepAlive -> auto-start on boot, self-heals).

| Command | Action |
|---|---|
| `launchctl list \| grep cloudflared` | Tunnel running? (PID) |
| `launchctl unload ~/Library/LaunchAgents/com.nomadomics.cloudflared.plist` | Stop tunnel |
| `launchctl load ~/Library/LaunchAgents/com.nomadomics.cloudflared.plist` | Start tunnel |
| `tail -f logs/cloudflared.err` | Tunnel logs |
| `cloudflared tunnel info nomadomics-strapi` | Connection status |

Config: `~/.cloudflared/config.yml` · Credentials: `~/.cloudflared/*.json` (SECRET)
Migration note: on Hetzner cutover, install cloudflared on the VPS with the same
tunnel ID + ingress (`service: http://strapi:1337`), then remove the local LaunchAgent.
Public URL never changes; Vercel env untouched.

## Vercel frontend env contract

```
STRAPI_URL=https://strapi.nomadomics.blog   # server-side data fetch
STRAPI_API_TOKEN=<read-only token>          # NOT the engine token
NEXT_PUBLIC_SITE_URL=https://nomadomics.blog
```
DNS plan: apex + www -> Vercel · strapi.* -> Cloudflare tunnel (done 2026-08-25)

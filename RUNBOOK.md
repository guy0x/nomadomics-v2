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

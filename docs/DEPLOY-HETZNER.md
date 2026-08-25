# DEPLOY — Hetzner VPS (Strapi) + Vercel (frontend)

> Prepared 2026-08-25 per Ship-the-Blog plan Task 6–7. Execute top-down.
> Secrets rule: tokens/PATs are created and pasted by **Guy** only, in terminal/admin panes.

## Architecture

```
[Vercel: Next.js 16 frontend]  --HTTPS-->  [Hetzner CX22: Strapi 5 + Postgres 16 (Docker)]
     NEXT_PUBLIC_SITE_URL                        api.nomadomics.<tld>
```

Frontend reads ONLY `status=published`; engine stays local writing drafts via
`STRAPI_ENGINE_TOKEN` pointed at the VPS URL after migration (update `~/nomadomics-v2/.env`
HOST/PORT when we cut over).

## Phase 1 — Provision VPS (Guy)

1. Hetzner Cloud → New server: **CX22**, Ubuntu 24.04, your SSH key, location EU.
2. `ssh root@<ip>` then:

```bash
apt update && apt -y upgrade
curl -fsSL https://get.docker.com | sh
ufw allow OpenSSH && ufw allow 80 && ufw allow 443 && ufw --force enable
```

3. DNS (registrar): `A api.<domain> → <vps-ip>` and later `A/CNAME @ + www → Vercel`.

## Phase 2 — Strapi + Postgres on VPS

```bash
mkdir -p /opt/nomadomics && cd /opt/nomadomics
# docker-compose.yml below; generate secrets ON THE SERVER:
openssl rand -base64 32   # repeat for each secret
```

`docker-compose.yml`:

```yaml
services:
  postgres:
    image: postgres:16
    restart: unless-stopped
    environment:
      POSTGRES_DB: nomadomics
      POSTGRES_USER: strapi
      POSTGRES_PASSWORD: ${PG_PASSWORD}
    volumes: [pgdata:/var/lib/postgresql/data]
  strapi:
    image: node:22-alpine   # build strapi/app via bind mount on first boot
    working_dir: /app
    restart: unless-stopped
    command: sh -c "npm ci && npm run build && npm start"
    environment:
      DATABASE_CLIENT: postgres
      DATABASE_HOST: postgres
      DATABASE_PORT: "5432"
      DATABASE_NAME: nomadomics
      DATABASE_USERNAME: strapi
      DATABASE_PASSWORD: ${PG_PASSWORD}
      JWT_SECRET: ${JWT_SECRET}
      ADMIN_JWT_SECRET: ${ADMIN_JWT_SECRET}
      APP_KEYS: ${APP_KEYS}
      API_TOKEN_SALT: ${API_TOKEN_SALT}
      TRANSFER_TOKEN_SALT: ${TRANSFER_TOKEN_SALT}
      HOST: 0.0.0.0
      PORT: "1337"
    volumes:
      - ./app:/app
      - ./uploads:/app/public/uploads
    depends_on: [postgres]
volumes:
  pgdata:
```

Copy the repo's `strapi-app` sources up (rsync `~/nomadomics-v2/{config,src,database,package.json}`),
excluding `.env`, `node_modules`, `logs`, `public/uploads`:

```bash
rsync -av --exclude node_modules --exclude .env --exclude logs \
  guy@<mac>/Users/guy/nomadomics-v2/ root@<vps>:/opt/nomadomics/app/
```

TLS: put Caddy (`caddy` image, automatic Let's Encrypt) in front proxying to `strapi:1337`,
or use Cloudflare proxied DNS with origin certs. Caddyfile:

```
api.<domain> {
  reverse_proxy strapi:1337
}
```

## Phase 3 — Migrate data (local → VPS)

From the Mac (creds come from `~/nomadomics-v2/.env`, never echoed):

```bash
# dump local
docker exec -it $(docker ps -qf name=postgres) pg_dump -U $DATABASE_USERNAME $DATABASE_NAME > nomado.dump
# OR native psql if installed locally
scp nomado.dump root@<vps>:/tmp/
ssh root@<vps> 'docker exec -i <pg-container> psql -U strapi nomadomics < /tmp/nomado.dump'
```

Verify on VPS: `/admin` → 200; article count = 18+; topic count = 25; admin login works
(admin users table came across in the dump).

## Phase 4 — Read-only API token (Guy, in VPS Strapi admin)

Admin Panel → Settings → API Tokens → create **`frontend-read`**:
- Token type: **Read-only**
- Copy value once — used in Phase 5 only.
⚠️ NOT the engine token. Engine token never leaves local `.env`.

## Phase 5 — Vercel (Guy imports, I verify)

1. vercel.com → Add New Project → import `guy0x/nomadomics-v2`, **root directory `frontend/`**.
2. Environment variables (Production):
   - `STRAPI_URL` = `https://api.<domain>`
   - `STRAPI_API_TOKEN` = value from Phase 4
   - `NEXT_PUBLIC_SITE_URL` = `https://<domain>` (drives sitemap/robots/canonicals)
3. Deploy. Verify: homepage 200; article pages render; `/sitemap.xml` lists published slugs.

Gate check: prod env must contain NO dev tokens (`localhost` URLs, engine token).

## Phase 6 — Domain + indexing

1. Registrar: apex + `www` → Vercel (`A 76.76.21.21` / `CNAME cname.vercel-dns.com` — follow
   Vercel's dashboard instructions exactly; they may differ by project).
2. Google Search Console → add property `https://<domain>` (DNS TXT verification) → submit
   `sitemap.xml` → Request indexing on the seed articles.

## Verification checklist (Definition of done)

```bash
env -u PYTHONPATH .venv/bin/python -m pytest tests/ -q        # still 34 passed
grep -rn 'else "published"' ~/nomadomics-v2/engine/           # no hits
git ls-remote --heads origin                                  # auth OK
curl -s "https://api.<domain>/api/articles?filters[status][$eq]=published" | jq '.meta.pagination.total'  # >=15
curl -s -o /dev/null -w "%{http_code}" https://<domain>       # 200
```

## After cutover

- Point local engine at VPS: set `HOST=api.<domain>` (and PORT scheme) in `~/nomadomics-v2/.env`;
  keep `STRAPI_ENGINE_TOKEN` unchanged only if tokens were migrated in the DB dump — otherwise
  create a new custom (write-limited) engine token in the VPS admin.
- Then schedule the daily cron (plan Task 8): `run-batch 2` at 09:00 + Telegram Cron-topic notify.

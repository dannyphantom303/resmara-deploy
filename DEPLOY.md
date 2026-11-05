# Deploying Resmara

Resmara is a **web application** — a FastAPI service plus a static frontend it serves itself.
There is no mobile app to build and nothing about the launch needs one, so "launch a website"
and "launch the product" are the same job here: one domain, one service, one database.

This document is the handoff for hosting it somewhere that is not the build machine.

---

## 1. What actually gets deployed

| Piece | What it is | Notes |
|---|---|---|
| `app` | One container (or one process) running `uvicorn app.main:app` | Serves the API under `/api`, the frontend at `/`, uploads at `/uploads`, docs at `/docs` |
| Database | Postgres (compose default) or sqlite for a single box | Schema migrations run automatically at startup |
| Uploads volume | Directory from `UPLOAD_DIR`, mounted at `/app/uploads` | **Must persist.** Instagram fetches post media over the public URL; there is no S3 backend in this app. `UPLOAD_DIR` is authoritative — the app writes there and serves `/uploads` from there |
| Domain + TLS | One https hostname | Meta needs a stable public origin; its OAuth callback and Instagram's media fetch both use it |
| LLM endpoint | Any OpenAI-compatible API (OpenAI, Azure, or self-hosted) | Without one the app still boots but the engine returns fixture copy and reports `source: "offline"` |

No separate scheduler process is bundled — the two recurring jobs call token-protected HTTP
endpoints, so any cron (host, container, or platform scheduler) will do (§6).

---

## 2. What has to be decided or obtained

Minimum to bring the site up:

- A host (§3) and a domain name.
- `SECRET_KEY` and `RESMARA_PUBLISH_TOKEN` — generated, not stored anywhere else.
- `RESMARA_TOKEN_KEY` — generated, and **backed up with the database**; it decrypts the stored Meta tokens, and losing it means every connected ad account must be reconnected by hand.
- An LLM endpoint + key (or a self-hosted model).

To take real client work, additionally:

- A Meta app with the host in **App domains**, the OAuth redirect registered, and privacy/terms URLs on the domain. The in-app Meta app (`META_CLIENT_ID` / `META_CLIENT_SECRET`) is currently the build machine's app — the partner should create **their own** app so a bad token or policy strike can't take down both.
- Publishing permissions: `pages_manage_posts`, `instagram_basic`, `instagram_content_publish` (App Review / Advanced Access), plus Business Verification and a Marketing API access tier.
- SMTP credentials for password-reset email (§8 — not configured, the reset flow returns the token instead of mailing it).
- A billing provider (§8 — there is none in the code; customers cannot pay through the app yet).

---

## 3. Where to host it

| Option | Cost | When it's right |
|---|---|---|
| **Small VPS + Docker Compose + Caddy** (recommended) | ~$6–12/month | Everything on one box, full control, cheapest at low scale. 2 vCPU / 4 GB is plenty for a handful of agents |
| Managed container host (Render, Railway, Fly.io, DigitalOcean App Platform) | ~$7–25/month + DB | You don't want to run a server: push the image, attach a persistent disk for `/app/uploads` and a managed Postgres |
| Kubernetes | — | Overkill for this, only if the partner already runs one |

WordPress or any PHP/CMS host is **not** an option: this is a Python service with a database,
uploaded media and an OAuth callback, so a CMS would just be a second system beside it.

A single box with `docker compose` for app + Postgres, `Caddy` in front for automatic TLS, and
nightly `pg_dump` + uploads copy is a complete, credible production setup at this scale.
The app is bind-ready at the domain root or behind a subpath — it detects its own mount prefix,
so `/` on a dedicated domain is fine.

---

## 4. Deploying with Docker Compose

On the host:

```bash
git clone <repo> resmara && cd resmara     # or unpack the tarball from scripts/make_deploy_bundle.sh
cp .env.example .env
$EDITOR .env                               # see §5 for the values that must change
docker compose up -d --build
docker compose logs -f app                 # expect: "[resmara] startup migrations: N columns added, M token(s) encrypted"
curl -I http://127.0.0.1:8000/             # 200 from the frontend
```

TLS in front (Caddy example, `/etc/caddy/Caddyfile`):

```
app.example.com {
    encode gzip
    reverse_proxy 127.0.0.1:8000
    request_body {
        max_size 100MB      # listing videos are uploaded through the API
    }
}
```

Then set the public URLs to the real host (§5) and restart: `docker compose up -d`.

Without Docker: `python -m venv .venv && .venv/bin/pip install -r requirements.txt` then
`.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers` under systemd.
The `venv/` in the build tree is a symlink to another project's virtualenv and must not be copied.

Note on volume ownership: the container starts as root only long enough to make `UPLOAD_DIR` and
the sqlite directory writable, then drops to uid 10001 before starting the server (see
`docker-entrypoint.sh`). That means a **bind mount** works without pre-chowning it — but if you
would rather it never run as root at all, pre-chown the host directory to `10001:10001` and add
`user: "10001:10001"` to the `app` service.

---

## 5. Required changes in `.env` for a real host

These five are the ones that make a deployment correct rather than merely running — everything
else is optional or has a working default:

```bash
SECRET_KEY=<openssl rand -hex 32>
RESMARA_ENV=production
RESMARA_PUBLIC_BASE_URL=https://app.example.com     # no trailing slash
META_REDIRECT_URI=https://app.example.com/api/oauth/meta/callback
RESMARA_PUBLISH_TOKEN=<openssl rand -base64 32>
RESMARA_TOKEN_KEY=<python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())">
```

Also set `DATABASE_URL` (the compose file overrides it anyway), a real `RESMARA_MODEL_*` set for
whichever LLM endpoint is configured, and `META_CLIENT_ID` / `META_CLIENT_SECRET` / `META_SCOPES`.
Changing any value requires a restart — everything is read at import time.

---

## 6. First run

```bash
# operator account (no admin route exists on purpose; the first one is made on the box)
docker compose exec app python scripts/create_operator.py \
    --email ops@example.com --password '<a real one>' --name Dana
```

Then browse `https://app.example.com/admin.html` (operator console: connections, health, metrics,
support tickets) and `https://app.example.com/` (the client app: sign in → property → build →
approve → launch). Client accounts are created with `POST /api/auth/register` or, from the
console, by the operator; the script above accepts `--no-admin` to make a plain client.

## 7. Scheduled jobs

Two recurring jobs keep a deployment honest. Both authenticate with the **`X-Resmara-Token`
header set to `RESMARA_PUBLISH_TOKEN`** (not a Bearer token, not a user session). Host crontab
example:

```cron
# publish every approved post whose time has come (every 15 min)
*/15 * * * * curl -fsS -X POST -H "X-Resmara-Token: $RESMARA_PUBLISH_TOKEN" https://app.example.com/api/content/publish/run >> /var/log/resmara-publish.log 2>&1

# refresh/verify Meta connections before their ~60-day tokens die (every 6 h)
17 */6 * * * curl -fsS -X POST -H "X-Resmara-Token: $RESMARA_PUBLISH_TOKEN" https://app.example.com/api/oauth/meta/check-all >> /var/log/resmara-token.log 2>&1
```

Both endpoints answer `503` when `RESMARA_PUBLISH_TOKEN` is unset and `403` when the header does
not match, so a misconfigured job fails loudly instead of silently doing nothing. The second job
is what flips an account to "needs reconnect" instead of letting a client's campaign quietly stop.

No watchdog is needed: `restart: unless-stopped` (or the platform's health check) covers restarts.
Uptime probes can hit `GET /` (200) — there is no dedicated `/health` route; real health signals
are at `GET /api/admin/health` behind an operator login.

## 8. Meta settings for the new domain

In the partner's own Meta app:

1. **App domains**: add the host of `RESMARA_PUBLIC_BASE_URL`.
2. **Facebook Login → Valid OAuth redirect URIs**: add `META_REDIRECT_URI` exactly.
3. **Privacy policy URL / Terms of service URL**: the app serves working pages at
   `/privacy.html` and `/terms.html` — point Meta at the new domain's copies of those.
4. **Use cases / permissions**: keep `META_SCOPES` in step with what is granted; Meta rejects the
   entire consent dialog if any single scope in the list is not enabled for the app.
5. Submit Business Verification and App Review for the publishing permissions above, and request
   the Marketing API access tier. Campaigns are always created **PAUSED**; only the client's own
   ad account holds a budget. Resmara is granted partner access and never touches client money.

## 9. Not ready for paying clients yet (be explicit with the partner)

- **No billing.** Nothing in the code charges anyone; `subscription_status` exists on the user row
  but no provider is wired. Subscriptions are manual or out of scope for launch.
- **No outbound email.** Password reset answers `delivery="not_configured"` and returns the token
  to the caller until `SMTP_*` is set.
- **Media lives on local disk.** Fine on a VPS with a volume; needs an object store before running
  more than one app replica, because Instagram fetches media by URL from whichever box wrote it.
- **Meta publishing permissions are pending** (§8). Ads and campaign creation work today; organic
  Facebook/Instagram posting does not until those scopes are granted.
- **Uploads are not virus-scanned** and are validated by file extension allow-list only — no content sniffing.
- **One app process** is assumed for the scheduler; run the publisher job once, not per replica.

## 10. Verifying a deployment

The repo ships its own checker — run it after every deploy, from any machine that can reach
the host:

```bash
python scripts/selfcheck.py --base https://app.example.com                 # read-only
python scripts/selfcheck.py --base https://app.example.com --full \
    --system-token "$RESMARA_PUBLISH_TOKEN"                                # full client flow
```

Read-only mode checks the API, the frontend, both legal pages, the operator console, and — with
`--system-token` — that the two scheduled endpoints reject a wrong token and accept the real one.
`--full` additionally registers a throwaway client, uploads `tests/fixtures/listing-photo.jpg`,
creates a campaign, runs a build, and confirms post media is reachable over the public URL. The
test campaign it leaves behind is never approved or launched; delete it from the console.

Before that, `./scripts/run_tests.sh` runs every isolated suite locally (it needs no server).

`--full` prints the engine `source` the build declared. **`source=offline` means no model is
configured** — the pipeline ran on fixture copy. That is fine on a smoke test and not fine on a
client-facing deployment, so treat it as a release blocker.

## 11. Backups and restore

```bash
docker compose exec db pg_dump -U resmara resmara > resmara-$(date +%F).sql
docker run --rm -v resmara_uploads:/u -v "$PWD":/b alpine tar czf /b/uploads-$(date +%F).tar.gz -C /u .
```

Restore is the reverse (restore the dump, untar uploads into the volume) — and it only works if
the **same `RESMARA_TOKEN_KEY`** is in the environment: without it, every stored Meta token is
unreadable and each client has to reconnect. Keep that key in a password manager alongside the
backups, never in the repo.

## 12. Launch checklist

- [ ] VPS (or PaaS) provisioned; Docker + compose installed
- [ ] Domain pointing at the host; Caddy (or platform TLS) serving https
- [ ] `.env` filled per §5; `SECRET_KEY`, `RESMARA_PUBLISH_TOKEN`, `RESMARA_TOKEN_KEY` generated
- [ ] `docker compose up -d --build`; startup migration line seen; `/` returns 200
- [ ] Operator account created (§6); operator console loads; `/admin.html` health cards populated
- [ ] LLM endpoint configured and a test campaign built (watch `source` in the build notes — it
      must not say `offline`)
- [ ] Meta app: app domains, redirect URI, privacy/terms URLs (§8)
- [ ] Both cron jobs installed and seen succeeding in their logs
- [ ] Nightly database + uploads backup running; `RESMARA_TOKEN_KEY` stored safely
- [ ] `scripts/selfcheck.py --full` passes and does **not** report `source=offline` (§10)
- [ ] A real client ad account connected end to end, one PAUSED campaign created, then a real
      publish once the posting permissions clear

# Resmara — Real Estate Boost Engine

Upload listing photos → AI builds a branded 14-day campaign from the handoff spec →
client approves → launch a real (PAUSED) Meta campaign → publish approved posts to the
Facebook Page and Instagram → day-7 / day-14 report pulled from the Graph API.

Running now on this machine: `http://127.0.0.1:8083` (public:
`https://sport.taila73942.ts.net/resmara/`, operator console `/resmara/admin.html`,
API explorer `/resmara/docs`).

**Hosting it somewhere else?** Read [`DEPLOY.md`](DEPLOY.md) — container/compose files,
the `.env` values a real host must set, the two scheduled jobs, the Meta settings for a new
domain, backups, and what is deliberately not built yet (billing, outbound email). Ship the
code with `./scripts/make_deploy_bundle.sh` (never includes `.env`, the database or uploads)
and verify any deployment, old or new, with `python scripts/selfcheck.py --base <url>`.

## Test

```sh
./scripts/run_tests.sh                     # every isolated suite; node tests skip if absent
PYTHON=venv/bin/python ./scripts/run_tests.sh
```

Live checks need a running server: `venv/bin/python tests/smoke_live.py` and
`python scripts/selfcheck.py --base http://127.0.0.1:8083 --full`.

## Run

```sh
cd /Users/dan/resmara
venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8083
```

On startup `app/db/migrate.py` adds any missing columns to the existing SQLite file, so a
stale `resmara.db` does not need to be deleted.

## Test

```sh
cd /Users/dan/resmara
PYTHONPATH=/Users/dan/resmara venv/bin/python tests/test_prototype.py
PYTHONPATH=/Users/dan/resmara venv/bin/python tests/test_plan_rules.py
PYTHONPATH=/Users/dan/resmara venv/bin/python tests/test_content_engine.py
PYTHONPATH=/Users/dan/resmara venv/bin/python tests/test_video_mix_repair.py
PYTHONPATH=/Users/dan/resmara venv/bin/python tests/test_ad_platforms.py
PYTHONPATH=/Users/dan/resmara venv/bin/python tests/test_credits.py
PYTHONPATH=/Users/dan/resmara venv/bin/python tests/test_insights.py
PYTHONPATH=/Users/dan/resmara venv/bin/python tests/test_publisher.py
PYTHONPATH=/Users/dan/resmara venv/bin/python tests/test_publisher_scope.py
PYTHONPATH=/Users/dan/resmara venv/bin/python tests/test_metrics.py      # operator numbers
PYTHONPATH=/Users/dan/resmara venv/bin/python tests/test_oauth_callback.py  # the browser's Meta redirect
PYTHONPATH=/Users/dan/resmara venv/bin/python tests/test_token_health.py  # tokens, spend readiness, the launch gate
node tests/test_frontend_api.js        # stubbed fetch: method, path, body of every UI call
node tests/test_deployed_ui.js         # the real api.js over the real public URL
```

No network and no API key are needed for the suites: the platform tests point the Graph
client at a local mock server, and the engine tests run in offline mode. Every suite runs
against its own throwaway sqlite file - a test must never migrate, encrypt or write to the
database the install is actually using.

Two of them talk to the running app instead, and prove the whole product rather than one
module. They create their own users and are safe to re-run:

```sh
PYTHONPATH=/Users/dan/resmara venv/bin/python tests/smoke_live.py       # 40 steps, simulated platform
PYTHONPATH=/Users/dan/resmara venv/bin/python tests/real_build_once.py "706 Congress Ave, Austin TX"
```

`smoke_live.py` walks register → ad account → boost → photo → AI tag → build → approve →
credit precheck → launch → publish → report → password reset → support desk (client raises a
request, the operator answers it, the client reads the reply) → operator metrics →
per-user isolation. It
uploads `tests/fixtures/listing-photo.jpg` — a real JPEG, because the vision model cannot
judge a 1x1 stub and Instagram refuses anything that is not a JPEG.
`test_deployed_ui.js` is the end-to-end one: it runs the real `static/api.js` in a sandbox
whose `fetch` hits `https://sport.taila73942.ts.net` for real, with `document.currentScript`
pointing at `/resmara/api.js` exactly as a browser sees it. It mints the Command Center
session cookie with `/Users/dan/Scripts/lib/cc-session.js` (the same library the router
verifies against), registers an account, logs in, creates a boost and lists them back. It is
the test that fails if the mount prefix is ever wrong again — the stubbed suite cannot catch
that, because a wrong-but-consistent path still passes a stub.

`real_build_once.py` is the only one that spends tokens: it runs the real models (R1/R3 use
`gpt-5.5` with web search) and prints the researched facts, the plan and the stored posts.
It needs a restart first — uvicorn does not reload.

`test_token_health.py` is the one to run after touching anything about Meta access. It drives
the real code paths against a mock Graph: ciphertext in the database and none in the API
response, a near-expiry token being re-exchanged, a refresh that buys nothing being reported
as such, an account with no payment method being refused, a revoked token being refused
*before* any Meta object is created, and a failed launch deleting its own half-created chain.

## What is real now, and what is not

Real:
- **Content engine** (`app/services/content_engine.py`, `prompts.py`) — R1 research → R2
  brand → R3 style recipe → R4 campaign plan, prompts kept verbatim from the handoff
  docs; the plan is validated against the spec's hard rules (`plan_rules.py`) and turned
  into scheduled `posts` rows.
- **Meta Graph client** (`app/services/ad_platforms.py`) — campaign → adset → creative →
  ad via `httpx`, always created PAUSED, `special_ad_categories: ["HOUSING"]`.
- **Launch gate** (`app/services/launch.py`, `credits.py`) — the Creatify two-layer gate
  (budget precheck + copy approval) and its
  `PENDING → PENDING_APPROVAL → APPROVED → DEPLOYED → LIVE` state machine.
- **Insights** (`app/services/insights.py`) — organic post metrics and paid ad numbers
  straight from the Graph API, per handoff doc 15 sections 9–10.
- **Publisher** (`app/services/publisher.py`) — claims approved+due posts and publishes
  them to the FB Page / IG account, with an idempotency guard.
- **Accounts** — register, login, profile, and a password-reset flow.
- **Front end** — `static/api.js` (`window.RM`) is the one place the UI talks to the API,
  with the Bearer token in localStorage. Paths are written **without** the mount prefix
  (`/api/boosts`) and the prefix is detected at load time from api.js's own `<script src>`
  (`""` when the app is served directly, `/resmara` behind the Command Center router),
  because a root-absolute `/api/boosts` from a page at `/resmara/` reaches the router and
  404s before it ever reaches this app. With nobody logged in the screens still fall back to
  their local demo data.

Still not wired to a live account (each is a config step, not a code gap):
- `OPENAI_API_KEY` — **set in `.env` and verified** against `gpt-5.5` / `gpt-5.4-mini` /
  `gpt-image-1`. Remove it and the engine falls back to **offline** mode: the pipeline runs
  end-to-end but the copy is a deterministic fixture and the response says
  `"source": "offline"` — it never pretends to have called a model.
- Meta credentials — `META_CLIENT_ID` / `META_CLIENT_SECRET` are set and a **real login has
  completed**: `GET /api/oauth/meta/connect` → facebook.com consent →
  `/api/oauth/meta/callback` stores a long-lived (~60 day) user token plus the Pages and
  linked Instagram professional accounts, and the accounts stop being `simulated`. Three
  settings in the Meta app are needed, and Meta's own error text names each one:
  **App domains** must contain the host that serves the app (`sport.taila73942.ts.net`),
  **Valid OAuth Redirect URIs** must contain
  `https://sport.taila73942.ts.net/resmara/api/oauth/meta/callback` exactly, and the app must
  be **published (Live), not in Development** — Meta refuses to create an ad creative from a
  development-mode app ("Ads creative post was created by an app that is in development
  mode"). Publishing in turn requires a **Privacy policy URL** that the open internet can
  fetch: `…/resmara/privacy.html` (and `…/terms.html`) are served publicly for exactly that
  reason — the router's login gate would otherwise answer Meta with a 302. Which permissions
  the consent dialog may ask for is `META_SCOPES` in `.env`: Meta rejects the *whole* dialog
  with "Invalid Scopes" if any single permission is not enabled for the app's use cases, so
  the list is kept to the entitled set: `ads_management`, `business_management`,
  `pages_read_engagement`, `pages_show_list`, plus `pages_manage_posts` (Page posting),
  `instagram_basic` and `instagram_content_publish` (Instagram publishing), which the
  "Manage everything on your Page" and "Manage messaging & content on Instagram" use cases
  entitle the app to at Standard Access. A scope is only requestable once its permission shows
  "Ready for testing" on the use case's Permissions and features list.
  Credit card details are never entered in the app: ads go out PAUSED and the ad account's
  own budget row is the only thing that gates spend.
- `SMTP_*` — password-reset emails. Until it is configured the reset request returns
  `delivery: "not_configured"` and hands back the token so the flow still completes.
- `RESMARA_PUBLISH_TOKEN` — already generated in `.env`; the 15-minute publisher cron and
  the 6-hourly connection-health job use it as the shared system token for
  `POST /api/content/publish/run` and `POST /api/oauth/meta/check-all`.

## Client-billed connections

The chosen production model is **client-billed**: the customer keeps their own Meta ad
account and their own card pays Meta; Resmara is granted access to manage it as a partner
and never touches money or float. That model makes two failures silent, and both of them
show up only as "my ads never ran", so both are now measured rather than assumed:

- **Our access dies.** A long-lived user token lasts about 60 days and nothing used to
  refresh or even notice it. `app/services/token_health.py` asks `debug_token` about the
  token it holds - valid? expiring when? which app? which scopes? - and re-exchanges it via
  Meta's documented `fb_exchange_token` grant when it is within a week of expiry (at most
  once a day per account, so a refusal cannot become an hourly retry loop).
  One honest catch, measured on the real account: **Meta accepted the refresh and returned a
  new token with the SAME expiry**, so the exchange does not always buy time. That is
  recorded (`token_refresh_note`) and the account stays `expiring` with the date it will die,
  rather than being reported as renewed. Reconnect is the only real fix once the 60 days are
  up.
- **The account cannot spend.** `spend_readiness()` reads Meta's own `account_status`,
  `disable_reason` and `funding_source_details`. A missing payment method is blamed on the
  client's card, not on Meta. Crucially, "Meta did not return the payment-method field" is
  reported as **unknown**, never as "no card" - inventing a problem is as wrong as missing
  one, and an unknown field does not by itself block a launch.

Three consequences in the code:

- **Layer-0 launch gate** (`app/services/launch.py`): before creating anything, the
  connection must be usable. Otherwise the launch is refused with the reason
  (`needs_reconnect` / `account_not_ready`) and an `Event` is written. A PAUSED campaign
  nobody can run or pause is worse than a clear refusal.
- **Partial-chain rollback** (`app/services/ad_platforms.py`): if the campaign is created and
  the ad set is then rejected (a HOUSING ad set without a bid, say), the half-created chain
  is deleted and the response lists exactly what was removed, so the customer's ad account is
  left as it was found.
- **Tokens encrypted at rest** (`app/core/crypto.py`): `AdAccount._access_token` /
  `_refresh_token` hold Fernet ciphertext while `access_token` / `refresh_token` stay
  transparent plaintext for callers. The key comes from `RESMARA_TOKEN_KEY` (set in `.env`,
  chmod 600 - **back this up**: losing it means every connection must be reconnected by
  hand); without it the key is derived from `SECRET_KEY`, so an install that never sets one
  still encrypts. Existing plaintext rows are upgraded on startup, and a token that cannot be
  decrypted raises instead of returning junk.

Migrations (`migrate()` and `encrypt_stored_tokens()`) run from the app's **startup** event.
They used to run at import time, which meant any script or test that imported `app.main`
would migrate - and re-encrypt - whatever database the environment pointed at. Importing a
module must never write to data.

**The health check runs on its own:** `scripts/resmara_token_health.py` (dev profile,
`no_agent`, every 6 hours) calls the sweep above and prints nothing when every connection is
healthy, one line per account that needs a human, and exits non-zero if any does. Run it by
hand with `python3 resmara_token_health.py --base http://127.0.0.1:8083`.

## Spec repairs the engine makes on its own

The planner is a model, so two hard rules occasionally come back broken. Both are repaired
deterministically before the plan is validated and stored, and every repair is reported in
the build response (`repairs`) and in the operator-visible `missingInfo`:

- **Video rhythm** (doc 10): fewer than a third video posts, or two videos adjacent. The
  engine rebuilds the kind pattern from the spec's own even spacing, keeps an existing hero
  (`main_video`), and gives any slot it demotes to a static the plan's `NEEDS PHOTO`
  placeholder. Note a 7-post campaign cannot satisfy both "at least a third" and "never more
  than two fifths" — for those lengths the ceiling yields to the floor, since
  "never more than two fifths" is the absolute rule.
- **A stale note** claiming the campaign has no video posts is dropped once the repair has
  added some.

## The operator flow

1. `POST /api/boosts` — create the boost (address, go-live date, campaign days, budget).
2. `POST /api/content/upload/photo` (or `/uploads`) — photos become `assets` rows.
3. `POST /api/content/assets/{boost_id}/tag` — AI tags them into the PHOTO INDEX.
4. `POST /api/boosts/{boost_id}/build` — the engine writes brand, style, plan and posts.
5. `GET /api/boosts/{boost_id}/plan` + `GET /api/boosts/{boost_id}/posts` — team review.
6. `POST /api/boosts/{boost_id}/approve` — client approval (unblocks publishing).
7. `POST /api/adflow/credits/precheck/` then `POST /api/launch`
   (`{platform:'meta', boost_id, auto_approve}`) — budget + copy gate, then the campaign
   is created PAUSED on Meta.
8. The publisher cron publishes approved posts when their time comes
   (`GET /api/content/publish/status/{boost_id}` to watch it).
9. `GET /api/content/reports/{boost_id}?day=7|14` — real numbers, or an explicit
   `source: "unavailable"`.

## API Endpoints

Auth (`/api/auth`): `POST /register`, `POST /login`, `GET /me`, `PATCH /me`,
`POST /me/password`, `POST /password-reset/request`, `POST /password-reset/confirm`.

Meta OAuth (`/api/oauth`): `POST /api/oauth/meta/connect` (returns the consent URL, never a
token), `GET /api/oauth/meta/callback` (reached by the browser, so no Authorization header),
`POST /api/oauth/meta/check-all` (system token; refreshes/re-checks every connection - this is
what the health job calls).

Boost engine: `POST /api/boosts/{id}/build`, `GET /api/boosts/{id}/plan`,
`GET /api/boosts/{id}/posts`, `POST /api/boosts/{id}/approve`,
`POST /api/boosts/{id}/launch`, `POST /api/adflow/credits/precheck/`.

Resmara core: `GET|POST /api/ad-accounts`,
`POST /api/ad-accounts/check-all` (re-check every connection the signed-in client owns),
`GET|POST /api/creatives`,
`PATCH /api/creatives/{id}/approve`, `GET|POST /api/boosts`, `GET /api/boosts/{id}`,
`POST /api/launch`, `POST /api/posts`, `GET /api/posts/{boost_id}`,
`PATCH /api/posts/{id}/approve`, `GET|POST /api/support`.

Content (`/api/content`): `POST /api/content/upload/photo`, `POST /api/content/uploads`,
`GET /api/content/assets/{boost_id}`, `POST /api/content/assets/{boost_id}/tag`,
`GET /api/content/photo-index/{boost_id}`, `POST /api/content/generate/content`,
`POST /api/content/publish/run` (token), `POST /api/content/publish/boost/{boost_id}`,
`GET /api/content/publish/status/{boost_id}`, `GET /api/content/reports/{boost_id}`.

Admin (`/api/admin/*`): `users`, `support`, `PATCH /support/{id}`, `health`, `metrics`.

## Operator console and the support desk

The console is `static/admin.html` (served at `/resmara/admin.html`) and it reads two
endpoints that deliberately do **not** overlap, so no figure is ever printed twice:

- **`GET /api/admin/health`** — is the service well? Status, database reachability, version
  and environment, errors in the last 24 hours, when the last campaign was built and
  launched, and whether content generation and the ad platform are **live** or
  **simulated**. It carries no product counts.
- **`GET /api/admin/metrics`** — what is the product doing? Grouped as `users`,
  `campaigns`, `content`, `support`, `advertising` and `activity` (14 days of event
  buckets), plus `unavailable`. It carries no service state.

Both are counted from rows that exist (see `app/services/metrics.py`); nothing is
extrapolated and nothing is estimated. Anything we genuinely cannot know is `null` and
named in `unavailable` with the reason — today that is `ad_spend` (no ad account carries a
real token) and `revenue` (no price is configured). `support.waiting_on_us` counts open
tickets whose newest message is not from an operator, so the queue cannot read as empty
while people are waiting.

The client's side is the **Support** page in the dashboard (`static/app.js`,
`supportPage()`), which lists the client's own requests and the replies. The in-page
assistant sends anything outside its guided answers to the same place ("Send to support"),
so a question asked in chat becomes a real ticket instead of a dead end. Both go through
`RM.createTicket()` / `RM.tickets()` in `static/api.js`.

## Configuration

Copy `.env.example` to `.env` and fill in what you have. Nothing is required to boot.

## Architecture

- **Database:** SQLite (`resmara.db`); column migrations in `app/db/migrate.py`
- **Auth:** JWT (register/login/reset), per-user ownership checks on every boost/post
- **Meta OAuth:** `state` is `"{user_id}:{hmac}"` signed with `SECRET_KEY`, because Meta
  redirects the *browser* to the callback and that request carries no Authorization header.
  The callback exchanges the code, immediately swaps the ~1-hour token for the long-lived
  one, stores the ad account(s) with the token's real expiry, resolves each account's Page
  and linked Instagram professional account, reports them, and bounces the browser back to
  `/?meta=connected`. `tests/test_oauth_callback.py` drives that exact no-credential request
  against a mock Graph endpoint.
- **Live launch, verified against a real ad account (2026-11-04):** boost 37
  (1420 Maple Grove Ave) launched through the real Marketing API on `act_254170201` —
  campaign `52584106135831`, ad set `52584106138831`, creative `1770457697582773`, ad
  `52584106144831`, all `status=PAUSED` with `special_ad_categories=[HOUSING]` and a
  $20/day campaign budget. The three payload rules that make it work are in
  `build_boost_configs`: the budget rides on the **campaign** (CBO — sending it on both is
  refused, subcode 1885621), the ad set always names a **bid cap** (`bid_strategy =
  LOWEST_COST_WITH_BID_CAP` + `bid_amount`, subcode 1815857 — even LOWEST_COST_WITHOUT_CAP
  is refused without a bid amount), and `advertiser_id` is stored exactly as Meta returns
  it (`act_…`), so it is never prefixed twice.
- **Photos:** local `uploads/` (served at `/uploads/<file>`); S3 is the production move
- **Ad spend:** every campaign is created PAUSED — nothing spends without a human
- **Scheduler:** `no_agent` cron jobs `resmara_publisher` (every 15m) +
  `resmara_watchdog` (every 5m, keeps the app up). Both are **paused while the Meta
  connection is being tested** — nothing restarts the app or publishes on a timer until
  they are resumed. In production the watchdog is replaced by the launchd agent
  `com.sport.resmara.plist` (RunAtLoad + KeepAlive) and the publisher by an in-process
  APScheduler job.

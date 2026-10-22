# Posting Dashboard — Shared Build Context
**Project:** V.R World Media posting dashboard (owned Metricool replacement)
**Root:** `~/workspace/posting-dashboard/`
**Primary spec:** `~/workspace/your_files/posting-dashboard-build-plan.md` — READ IT FIRST, follow it exactly.
This file is the integration contract. Every workstream reads this before writing code.

## Brands & platforms
- Brands: `quiet_position` ("Faceless Wicks (Quiet Position)" — YouTube @facelesswicksofficial, login Yosego.streaming@gmail.com), `the_odds_board` ("The Odds Board" — YouTube @OddsBoardofficial, login hqtheoddsboard@gmail.com), `heist` ("heistHQ365" — YouTube @Heisthq365official, login hqheist375@gmail.com), `jose_personal` (@yos_ego), `mh_outlanders` ("MH Outlanders" — YouTube "HuntersVaultOfficial" @huntersvaultofficial (brand name MH Outlanders), login hqheist375@gmail.com — CONNECTED 2026-10-21, channel UCE9Rr06IYOqJ28NDrkO5PNw)
- Platforms: `tiktok`, `x`, `instagram`, `youtube`

## Directory ownership (write ONLY to your assigned paths)
- **Backend:** `app/` (all Python incl. `app/main.py`, `app/db.py`, `app/models.py`, `app/scheduler.py`, `app/tokenstore.py`, `app/compliance.py`, `app/routes.py`), `adapters/base.py`, `requirements.txt`, `.env.example`, `run.sh`, `scripts/smoke_test.py`. Do NOT create `adapters/__init__.py` or the four platform modules. Do NOT overwrite `app/data/composer_data.json` (frontend owns content; backend only reads it).
- **Adapters:** `adapters/__init__.py`, `adapters/tiktok.py`, `adapters/x.py`, `adapters/instagram.py`, `adapters/youtube.py`. Import the base class from `adapters.base` (backend provides it).
- **Frontend:** `static/` (`index.html`, `upload.html`, `compose.html`, `approve.html`, `audit.html`, `app.js`, `style.css`) + content file `app/data/composer_data.json`.
- **Docs:** `README.md`, `docs/SETUP.md`, `docs/MEDIA_HOSTING.md`, `docs/CREDENTIAL_CHECKLIST.md`.

## Python stack ($0, all free, pip-installable)
`fastapi`, `uvicorn`, `python-multipart`, `cryptography`. No other dependencies. No paid services.

## Env vars
- `VRWM_FERNET_KEY` — Fernet key for token encryption. Generated once via `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. NEVER committed, never in code/logs.
- `VRWM_MOCK_ADAPTERS=1` — adapters simulate publish success, no network. Used for smoke tests.
- `VRWM_DB_PATH` — default `data/hub.db` under project root.
- `VRWM_MEDIA_DIR` — default `media/` under project root.
- `VRWM_PORT` — default `8077`.

## Adapter base class (backend writes `adapters/base.py`; adapters implement it EXACTLY)
```python
class BaseAdapter:
    platform: str  # "tiktok" | "x" | "instagram" | "youtube"
    def auth_url(self, redirect_uri: str, state: str) -> str: ...
    def exchange_code(self, code: str, redirect_uri: str) -> dict:
        # -> {"access_token": str, "refresh_token": str|None, "expires_in": int,
        #     "platform_user_id": str, "scopes": str}
    def refresh(self, refresh_token: str) -> dict:  # same shape as exchange_code
    def publish(self, post: dict, media_path: str) -> dict:
        # post = {"title": str, "caption": str, "hashtags": [str],
        #         "scheduled_at": str|None (ISO), "account": {"platform_user_id": str, ...},
        #         "thumbnail_notes": str, "labels_concept_art": bool}
        # -> {"ok": bool, "platform_post_id": str|None, "error": str|None, "cost_usd": float}
    def supports_native_scheduling(self) -> bool: ...
    def estimate_cost_usd(self, post: dict) -> float: ...
```
Mock rule: if `os.environ.get("VRWM_MOCK_ADAPTERS") == "1"`, `publish()` must return
`{"ok": True, "platform_post_id": "mock_<platform>_<8 hex>", "error": None, "cost_usd": estimate}`
with ZERO network calls. `auth_url`/`exchange_code`/`refresh` may also short-circuit in mock mode.

## REST API contract (backend implements; frontend consumes)
- `GET /api/accounts` → `[{id, brand, platform, platform_user_id, display_name}]`
- `POST /api/accounts` `{brand, platform, display_name}` → account (platform_user_id filled after OAuth)
- `POST /api/accounts/{id}/oauth/start` `{redirect_uri}` → `{auth_url}`
- `GET /api/accounts/{id}/oauth/callback?code=...&redirect_uri=...` → stores encrypted tokens, returns account
- `POST /api/upload` (multipart `file`) → `{media_id, filename}`
- `POST /api/posts` `{media_id, account_ids[], title, caption, hashtags[], thumbnail_notes, scheduled_at|null, labels_concept_art}` → post (status `draft`)
- `GET /api/posts?status=` → list
- `GET /api/posts/{id}` → post detail incl. compliance warnings
- `POST /api/posts/{id}/submit` → runs compliance: blocks → stays `draft` + `{errors}`; else → `pending_approval`
- `POST /api/posts/{id}/approve` `{note}` → `approved`
- `POST /api/posts/{id}/reject` `{note}` → `draft`
- `POST /api/compliance/check` `{brand, title, caption, hashtags[]}` → `{blocks[], warnings[]}`
- `GET /api/composer-data` → contents of `app/data/composer_data.json` (`{title_formulas[], thumbnail_checklist[], hook_templates[], platform_limits{}}`); return empty lists if file missing
- `GET /api/audit?post_id=` → `[{id, post_id, account_id, event, detail, created_at}]`
- `GET /api/x-spend` → `{month, posts, link_posts, estimated_usd}` (from audit log; informational)
- Static frontend served from `/` → `static/`. Media previews from `/media/` → `VRWM_MEDIA_DIR`.

## Post lifecycle
`draft` → `pending_approval` → `approved` → `scheduled`/`published` | `failed`. Every transition + publish attempt + token refresh is written to `audit_log`. Scheduler (background thread, 60s tick): picks posts with status `approved` where `scheduled_at` is null or <= now → decrypts tokens → refreshes if expiring within 5 min (IG: refresh if < 7 days left) → `adapter.publish()` → `published` (store platform_post_id) or `failed` (store error). YouTube adapter receives `scheduled_at` and uses native `publishAt`; all others publish immediately when the scheduler fires them.

## SQLite schema (backend creates on startup)
- `accounts(id, brand, platform, platform_user_id, display_name, created_at)`
- `tokens(account_id PK, access_token_enc, refresh_token_enc, expires_at, scopes, updated_at)` — tokens encrypted with Fernet; never logged
- `media(id, filename, path, mime, size_bytes, uploaded_at)`
- `posts(id, media_id, account_id, title, caption, hashtags, thumbnail_notes, labels_concept_art, scheduled_at, status, platform_post_id, error, cost_usd, created_at, updated_at)`
- `approvals(id, post_id, action, note, decided_at)`
- `audit_log(id, post_id, account_id, event, detail, created_at)`

## Compliance engine (backend `app/compliance.py`)
`check_post(brand, title, caption, hashtags) -> {"blocks": [...], "warnings": [...]}` — each item `{"rule": str, "message": str}`. Case-insensitive substring matching.
- `quiet_position`: BLOCK on broker/affiliate fingerprints: "pocket option", "quotex", "iq option", "binomo", "olymp trade", "olymptrade", "exnova", "deriv.com", "deposit bonus", "affiliate link", "sign up with my link", "broker". WARN on "guaranteed", "get rich", "100% win", "risk-free", "can't lose".
- `the_odds_board`: BLOCK on gambling fingerprints: "draftkings", "fanduel", "bet365", "caesars", "betmgm", "pointsbet", "unibet", "william hill", "ladbrokes", "paddy power", "promo code", "free bet", "deposit bonus", "oddsportal". WARN on "lock of the", "guaranteed", "can't lose".
- `heist`: WARN "Heist posts must label concept/fan art" unless `labels_concept_art` is true → then no warning. (Frontend shows a required checkbox for heist.)
- `mh_outlanders`: no brand-specific block/warn fingerprints (empty lists in `app/compliance.py`); all-brands rules still apply. Frontend hint: label concept/fan art, credit Capcom/TiMi for official material.
- All brands: WARN on "financial advice" unless the required disclaimer negation is present ("not financial advice" / "not betting or financial advice" / "not-financial-advice" — then it passes); platform hashtag limits: tiktok ≤100 hashtags (block if over), x ≤4 recommended (warn if over).
- The `submit` endpoint: any blocks → stays `draft`, returns blocks. Warnings → `pending_approval` with warnings stored on the post.

## Platform research (adapters + docs use this; NO live calls, NO real credentials)
### TikTok
- OAuth: Auth Code + PKCE (S256). Authorize `GET https://www.tiktok.com/v2/auth/authorize/` → exchange `POST https://open.tiktokapis.com/v2/oauth/token/`. Scopes (comma-separated): `user.info.basic`, `video.upload`, `video.publish`. Access 24h (86400s), refresh 365 days. Refresh: `POST /v2/oauth/token/` with `grant_type=refresh_token`. Revoke: `POST /v2/oauth/revoke/`.
- Per-user tokens keyed by `open_id`. Client key/secret from env placeholders `TIKTOK_CLIENT_KEY`, `TIKTOK_CLIENT_SECRET` (never hardcoded).
- Endpoints: `POST /v2/post/publish/video/init/` (Direct Post, needs audit); `POST /v2/post/publish/inbox/video/init/` (drafts fallback); `POST /v2/post/publish/content/init/` (photo, `media_type: PHOTO`); `POST /v2/post/publish/status/fetch/`; `POST /v2/post/publish/creator_info/query/` (call pre-post, display nickname).
- Upload: FILE_UPLOAD ≤4GB, or PULL_FROM_URL (HTTPS, verified domain). >64MB chunked (5–64MB chunks, sequential, max 1000). Caption ≤2200 chars, ≤100 hashtags.
- Config flag `TIKTOK_DIRECT_POST=false` default → use inbox/drafts until audit passes; flip to true with no code change.
- No native scheduling. Free.
### X
- OAuth 2.0 + PKCE. Authorize `GET https://api.x.com/2/oauth2/authorize` → token/refresh `POST https://api.x.com/2/oauth2/token`. Access 2h; refresh via `refresh_token` (needs `offline.access` scope).
- `POST /2/tweets` (text ≤280 graphemes, URLs count 23; `media.media_ids`; threads = sequential calls). `POST /2/media/upload` (v2): ≤4 images (5MB ea), 1 video (512MB, ≤140s), 1 GIF (15MB). Image+video in one tweet = rejected (validate in adapter).
- Cost: $0.015/post, $0.20/link post, $0.005/post read. Meter per publish; `estimate_cost_usd` returns 0.015 or 0.20 if post has URL. Client id/secret from env `X_CLIENT_ID`, `X_CLIENT_SECRET`.
- No native scheduling. Prepaid credits; reads minimized.
### Instagram
- Meta OAuth 2.0 server-side only. `GET https://www.facebook.com/v21.0/dialog/oauth?client_id=…&redirect_uri=…&scope=instagram_basic,instagram_content_publish,pages_show_list,pages_read_engagement`. Exchange code → short-lived (~1–2h) at `GET https://graph.facebook.com/v21.0/oauth/access_token` → long-lived (~60d) via `grant_type=fb_exchange_token` → refresh via `grant_type=ig_refresh_token` (token ≥24h old).
- Requirements: IG Business account linked to its own FB Page.
- Two-step: `POST /{ig-user-id}/media` (`media_type=REELS`, `video_url`, `caption`) → poll `status_code` until `FINISHED` → `POST /{ig-user-id}/media_publish`. Stories: `media_type=STORIES` (≤60s). Reels: 3–90s, 9:16, MP4.
- `video_url` MUST be fully public (no auth/bot protection) — adapter must ERROR clearly if given a non-public URL; docs cover the R2 hosting step. Config `VRWM_PUBLIC_MEDIA_BASE_URL` (empty until Jose sets hosting).
- Quota: 25 API posts/24h rolling per account; check `GET /{ig-user-id}/content_publishing_limit`.
- No native scheduling. Free. App id/secret from env `META_APP_ID`, `META_APP_SECRET`.
### YouTube
- Google OAuth 2.0. Scope `https://www.googleapis.com/auth/youtube.upload` (sensitive). NO service accounts. Access 1h; refresh effectively permanent once consent screen is in Production (Testing mode tokens die ~7 days — warn in docs).
- `videos.insert` (resumable: POST metadata → Location URL → PUT chunks), `thumbnails.set`, `videos.update`. Vertical <60s auto-Shorts.
- NATIVE scheduling: `status.publishAt` (RFC3339 UTC) + `status.privacyStatus: "private"` in `videos.insert`. `publishAt` with `public` is silently ignored — adapter must always pair with `private`.
- Quota ~100 uploads/day; unverified projects forced PRIVATE (docs must say: start verification day one). Free. Client id/secret from env `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`.

## Hard constraints (all workstreams)
- $0 stack. No paid deps/services. No real credentials, tokens, or keys in code, files, or logs — env placeholders only. No spending, publishing, or external submissions — build only. No live API calls except in clearly-marked real paths that require Jose's keys (default everything to mock/off).
- Dashboard binds `127.0.0.1` by default. MVP has no login — document as localhost-only; hardening is a later phase.
- Portability: must run on this Linux runtime AND on WSL2 Ubuntu (docs cover both).

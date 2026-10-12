"""All REST endpoints from the integration contract."""

import json
import logging
import html
import os
import re
import secrets
import traceback
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, File, HTTPException, Query, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse

from . import compliance as compliance_mod
from . import db as dbmod
from . import tokenstore
from . import youtube_quota
from . import yt_oauth
from .scheduler import load_adapter

log = logging.getLogger("vrwm.routes")
router = APIRouter()

BRANDS = {"quiet_position", "the_odds_board", "heist", "jose_personal"}
PLATFORMS = {"tiktok", "x", "instagram", "youtube"}

_URL_RE = re.compile(r"https?://|www\.")


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _media_dir() -> Path:
    raw = os.environ.get("VRWM_MEDIA_DIR", "media")
    p = Path(raw)
    if not p.is_absolute():
        p = Path(__file__).resolve().parent.parent / p
    p.mkdir(parents=True, exist_ok=True)
    return p


def _parse_hashtags(raw) -> list:
    if not raw:
        return []
    if isinstance(raw, list):
        return [str(h) for h in raw]
    try:
        val = json.loads(raw)
        return [str(h) for h in val] if isinstance(val, list) else []
    except (TypeError, ValueError):
        return []


def _account_json(row) -> dict:
    return {
        "id": row["id"],
        "brand": row["brand"],
        "platform": row["platform"],
        "platform_user_id": row["platform_user_id"],
        "display_name": row["display_name"],
    }


def _post_json(row, account=None) -> dict:
    d = {
        "id": row["id"],
        "media_id": row["media_id"],
        "account_id": row["account_id"],
        "title": row["title"],
        "caption": row["caption"],
        "hashtags": _parse_hashtags(row["hashtags"]),
        "thumbnail_notes": row["thumbnail_notes"],
        "labels_concept_art": bool(row["labels_concept_art"]),
        "scheduled_at": row["scheduled_at"],
        "status": row["status"],
        "platform_post_id": row["platform_post_id"],
        "error": row["error"],
        "cost_usd": row["cost_usd"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }
    if account is not None:
        d["account"] = _account_json(account)
    return d


def _get_account(db, account_id: int):
    row = db.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="account not found")
    return row


def _get_post(db, post_id: int):
    row = db.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="post not found")
    return row


def _audit(db, post_id, account_id, event, detail=None):
    db.execute(
        "INSERT INTO audit_log(post_id, account_id, event, detail, created_at)"
        " VALUES (?, ?, ?, ?, ?)",
        (
            post_id,
            account_id,
            event,
            json.dumps(detail, default=str) if detail is not None else None,
            _utcnow_iso(),
        ),
    )


def _run_compliance(post_row, account_row) -> dict:
    """Brand rules + platform hashtag limits + Heist label rule."""
    hashtags = _parse_hashtags(post_row["hashtags"])
    result = compliance_mod.check_post(
        account_row["brand"],
        post_row["title"],
        post_row["caption"],
        hashtags,
    )
    limits = compliance_mod.check_hashtag_limits(account_row["platform"], hashtags)
    result["blocks"].extend(limits["blocks"])
    result["warnings"].extend(limits["warnings"])
    label_warn = compliance_mod.heist_label_warning(bool(post_row["labels_concept_art"]))
    if account_row["brand"] == "heist" and label_warn:
        result["warnings"].append(label_warn)
    return result


# ---------------------------------------------------------------- accounts

@router.get("/api/accounts")
def list_accounts():
    with dbmod.get_db() as db:
        rows = db.execute("SELECT * FROM accounts ORDER BY id").fetchall()
    return [_account_json(r) for r in rows]


@router.post("/api/accounts")
def create_account(body: dict):
    brand = (body.get("brand") or "").lower()
    platform = (body.get("platform") or "").lower()
    display_name = body.get("display_name") or ""
    if brand not in BRANDS:
        raise HTTPException(status_code=400, detail=f"brand must be one of {sorted(BRANDS)}")
    if platform not in PLATFORMS:
        raise HTTPException(status_code=400, detail=f"platform must be one of {sorted(PLATFORMS)}")
    now = _utcnow_iso()
    with dbmod.get_db() as db:
        cur = db.execute(
            "INSERT INTO accounts(brand, platform, platform_user_id, display_name, created_at)"
            " VALUES (?, ?, NULL, ?, ?)",
            (brand, platform, display_name, now),
        )
        account_id = cur.lastrowid
        _audit(db, None, account_id, "account_created",
               {"brand": brand, "platform": platform, "display_name": display_name})
        row = db.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
    return _account_json(row)


@router.post("/api/accounts/{account_id}/oauth/start")
def oauth_start(account_id: int, body: dict):
    redirect_uri = body.get("redirect_uri") or ""
    if not redirect_uri:
        raise HTTPException(status_code=400, detail="redirect_uri is required")
    with dbmod.get_db() as db:
        account = _get_account(db, account_id)
    adapter = load_adapter(account["platform"])
    if adapter is None:
        raise HTTPException(status_code=503, detail="platform adapter not installed")
    state = secrets.token_urlsafe(16)
    return {"auth_url": adapter.auth_url(redirect_uri, state), "state": state}


@router.get("/api/accounts/{account_id}/oauth/callback")
def oauth_callback(account_id: int, code: str = Query(...), redirect_uri: str = Query(...)):
    """Exchange the OAuth code, store encrypted tokens, set platform_user_id,
    audit the event. Works in mock mode (adapter short-circuits)."""
    with dbmod.get_db() as db:
        account = _get_account(db, account_id)
    adapter = load_adapter(account["platform"])
    if adapter is None:
        raise HTTPException(status_code=503, detail="platform adapter not installed")
    try:
        result = adapter.exchange_code(code, redirect_uri) or {}
    except Exception as exc:
        log.warning("exchange_code failed for account %s: %s", account_id, exc)
        raise HTTPException(status_code=502, detail=f"token exchange failed: {exc}")
    try:
        tokenstore.store_tokens(account_id, result)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"failed to store tokens: {exc}")
    platform_user_id = result.get("platform_user_id")
    with dbmod.get_db() as db:
        db.execute(
            "UPDATE accounts SET platform_user_id = ? WHERE id = ?",
            (platform_user_id, account_id),
        )
        # Never log token values — only metadata.
        _audit(db, None, account_id, "oauth_complete",
               {"platform_user_id": platform_user_id, "scopes": result.get("scopes"),
                "expires_in": result.get("expires_in")})
        row = db.execute("SELECT * FROM accounts WHERE id = ?", (account_id,)).fetchone()
    return _account_json(row)


# ---------------------------------------------------------------- upload

@router.post("/api/upload")
async def upload_media(file: UploadFile = File(...)):
    data = await file.read()
    safe_name = os.path.basename(file.filename or "upload.bin") or "upload.bin"
    stored = f"{uuid.uuid4().hex}_{safe_name}"
    dest = _media_dir() / stored
    dest.write_bytes(data)
    now = _utcnow_iso()
    with dbmod.get_db() as db:
        cur = db.execute(
            "INSERT INTO media(filename, path, mime, size_bytes, uploaded_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (safe_name, str(dest), file.content_type, len(data), now),
        )
        media_id = cur.lastrowid
    return {"media_id": media_id, "filename": safe_name}


# ---------------------------------------------------------------- posts

@router.post("/api/posts")
def create_post(body: dict):
    """Create one draft post per account_id (schema stores one account per post)."""
    media_id = body.get("media_id")
    account_ids = body.get("account_ids") or []
    if not account_ids:
        raise HTTPException(status_code=400, detail="account_ids must be a non-empty list")
    title = body.get("title") or ""
    caption = body.get("caption") or ""
    hashtags = body.get("hashtags") or []
    thumbnail_notes = body.get("thumbnail_notes") or ""
    scheduled_at = body.get("scheduled_at")
    labels_concept_art = bool(body.get("labels_concept_art"))
    now = _utcnow_iso()
    created = []
    with dbmod.get_db() as db:
        if media_id is not None:
            m = db.execute("SELECT id FROM media WHERE id = ?", (media_id,)).fetchone()
            if m is None:
                raise HTTPException(status_code=400, detail="media_id not found")
        for account_id in account_ids:
            account = _get_account(db, account_id)
            cur = db.execute(
                """INSERT INTO posts(media_id, account_id, title, caption, hashtags,
                                     thumbnail_notes, labels_concept_art, scheduled_at,
                                     status, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'draft', ?, ?)""",
                (
                    media_id, account_id, title, caption, json.dumps(hashtags),
                    thumbnail_notes, int(labels_concept_art), scheduled_at, now, now,
                ),
            )
            post_id = cur.lastrowid
            _audit(db, post_id, account_id, "post_created",
                   {"title": title, "scheduled_at": scheduled_at})
            row = db.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()
            created.append(_post_json(row, account))
    return {"posts": created}


@router.get("/api/posts")
def list_posts(status: str | None = Query(default=None)):
    with dbmod.get_db() as db:
        if status:
            rows = db.execute(
                "SELECT p.*, a.brand AS _brand, a.platform AS _platform,"
                " a.platform_user_id AS _puid, a.display_name AS _dname"
                " FROM posts p JOIN accounts a ON p.account_id = a.id"
                " WHERE p.status = ? ORDER BY p.id DESC",
                (status,),
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT p.*, a.brand AS _brand, a.platform AS _platform,"
                " a.platform_user_id AS _puid, a.display_name AS _dname"
                " FROM posts p JOIN accounts a ON p.account_id = a.id"
                " ORDER BY p.id DESC",
            ).fetchall()
        out = []
        for r in rows:
            d = _post_json(r)
            d["account"] = {
                "id": r["account_id"], "brand": r["_brand"], "platform": r["_platform"],
                "platform_user_id": r["_puid"], "display_name": r["_dname"],
            }
            out.append(d)
    return out


@router.get("/api/posts/{post_id}")
def get_post(post_id: int):
    """Post detail including live compliance warnings/blocks."""
    with dbmod.get_db() as db:
        post = _get_post(db, post_id)
        account = _get_account(db, post["account_id"])
        comp = _run_compliance(post, account)
        d = _post_json(post, account)
    d["compliance"] = comp
    return d


@router.post("/api/posts/{post_id}/submit")
def submit_post(post_id: int):
    """Run compliance. Blocks -> stays draft + {errors}; else -> pending_approval."""
    with dbmod.get_db() as db:
        post = _get_post(db, post_id)
        account = _get_account(db, post["account_id"])
        comp = _run_compliance(post, account)
        now = _utcnow_iso()
        if comp["blocks"]:
            _audit(db, post_id, post["account_id"], "submit_blocked",
                   {"blocks": comp["blocks"]})
            db.commit()
            return JSONResponse(
                status_code=422,
                content={"ok": False, "errors": comp["blocks"],
                         "warnings": comp["warnings"], "status": "draft"},
            )
        db.execute(
            "UPDATE posts SET status = 'pending_approval', updated_at = ? WHERE id = ?",
            (now, post_id),
        )
        _audit(db, post_id, post["account_id"], "submitted",
               {"warnings": comp["warnings"]})
        db.commit()
        row = db.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()
    return {"ok": True, "status": "pending_approval",
            "warnings": comp["warnings"], "post": _post_json(row, account)}


@router.post("/api/posts/{post_id}/approve")
def approve_post(post_id: int, body: dict | None = None):
    note = (body or {}).get("note")
    now = _utcnow_iso()
    with dbmod.get_db() as db:
        post = _get_post(db, post_id)
        if post["status"] not in ("pending_approval", "draft"):
            raise HTTPException(
                status_code=409,
                detail=f"cannot approve a post with status '{post['status']}'",
            )
        db.execute(
            "UPDATE posts SET status = 'approved', updated_at = ? WHERE id = ?",
            (now, post_id),
        )
        db.execute(
            "INSERT INTO approvals(post_id, action, note, decided_at)"
            " VALUES (?, 'approve', ?, ?)",
            (post_id, note, now),
        )
        _audit(db, post_id, post["account_id"], "approved", {"note": note})
        account = _get_account(db, post["account_id"])
        row = db.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()
    return {"ok": True, "status": "approved", "post": _post_json(row, account)}


@router.post("/api/posts/{post_id}/reject")
def reject_post(post_id: int, body: dict | None = None):
    note = (body or {}).get("note")
    now = _utcnow_iso()
    with dbmod.get_db() as db:
        post = _get_post(db, post_id)
        db.execute(
            "UPDATE posts SET status = 'draft', updated_at = ? WHERE id = ?",
            (now, post_id),
        )
        db.execute(
            "INSERT INTO approvals(post_id, action, note, decided_at)"
            " VALUES (?, 'reject', ?, ?)",
            (post_id, note, now),
        )
        _audit(db, post_id, post["account_id"], "rejected", {"note": note})
        account = _get_account(db, post["account_id"])
        row = db.execute("SELECT * FROM posts WHERE id = ?", (post_id,)).fetchone()
    return {"ok": True, "status": "draft", "post": _post_json(row, account)}


@router.delete("/api/posts/{post_id}")
def delete_post(post_id: int):
    """Delete a draft post. Only drafts can be deleted (409 otherwise)."""
    with dbmod.get_db() as db:
        post = _get_post(db, post_id)
        if post["status"] != "draft":
            raise HTTPException(
                status_code=409,
                detail=f"cannot delete a post with status '{post['status']}'",
            )
        _audit(db, post_id, post["account_id"], "post_deleted",
               {"title": post["title"]})
        db.execute("DELETE FROM posts WHERE id = ?", (post_id,))
        db.commit()
    return {"ok": True}


# ---------------------------------------------------------------- compliance

@router.post("/api/compliance/check")
def compliance_check(body: dict):
    """Standalone compliance check. Optional extras: platform (hashtag limits),
    labels_concept_art (Heist rule) — both backward-compatible."""
    brand = (body.get("brand") or "").lower()
    title = body.get("title") or ""
    caption = body.get("caption") or ""
    hashtags = body.get("hashtags") or []
    result = compliance_mod.check_post(brand, title, caption, hashtags)
    platform = (body.get("platform") or "").lower()
    if platform in PLATFORMS:
        limits = compliance_mod.check_hashtag_limits(platform, hashtags)
        result["blocks"].extend(limits["blocks"])
        result["warnings"].extend(limits["warnings"])
    if brand == "heist" and "labels_concept_art" in body:
        warn = compliance_mod.heist_label_warning(bool(body.get("labels_concept_art")))
        if warn:
            result["warnings"].append(warn)
    return result


# ---------------------------------------------------------------- composer data

@router.get("/api/composer-data")
def composer_data():
    """Contents of app/data/composer_data.json; empty lists if missing/unreadable."""
    path = Path(__file__).resolve().parent / "data" / "composer_data.json"
    fallback = {
        "title_formulas": [],
        "thumbnail_checklist": [],
        "hook_templates": [],
        "platform_limits": {},
    }
    if not path.exists():
        return fallback
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeDecodeError):
        return fallback
    for key, default in fallback.items():
        data.setdefault(key, default)
    return data


# ---------------------------------------------------------------- audit + spend

@router.get("/api/audit")
def audit_list(post_id: int | None = Query(default=None)):
    with dbmod.get_db() as db:
        if post_id is not None:
            rows = db.execute(
                "SELECT * FROM audit_log WHERE post_id = ? ORDER BY id", (post_id,)
            ).fetchall()
        else:
            rows = db.execute(
                "SELECT * FROM audit_log ORDER BY id DESC LIMIT 500"
            ).fetchall()
    return [
        {
            "id": r["id"], "post_id": r["post_id"], "account_id": r["account_id"],
            "event": r["event"], "detail": r["detail"], "created_at": r["created_at"],
        }
        for r in rows
    ]


@router.get("/api/x-spend")
def x_spend():
    """Informational X spend for the current month, derived from the audit log."""
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    with dbmod.get_db() as db:
        rows = db.execute(
            """SELECT p.id, p.caption, p.cost_usd
               FROM audit_log al
               JOIN posts p ON p.id = al.post_id
               JOIN accounts a ON a.id = p.account_id
               WHERE al.event = 'published'
                 AND a.platform = 'x'
                 AND substr(al.created_at, 1, 7) = ?
               GROUP BY p.id""",
            (month,),
        ).fetchall()
    posts = len(rows)
    link_posts = sum(1 for r in rows if _URL_RE.search(r["caption"] or ""))
    estimated = round(sum((r["cost_usd"] if r["cost_usd"] is not None else 0.015) for r in rows), 4)
    return {"month": month, "posts": posts, "link_posts": link_posts,
            "estimated_usd": estimated}


# ---------------------------------------------------------------- youtube

def _youtube_accounts():
    """YouTube accounts with connection state (tokens present => connected)."""
    with dbmod.get_db() as db:
        rows = db.execute(
            "SELECT * FROM accounts WHERE platform = 'youtube' ORDER BY id"
        ).fetchall()
        out = []
        for r in rows:
            t = db.execute(
                "SELECT account_id FROM tokens WHERE account_id = ?", (r["id"],)
            ).fetchone()
            out.append({
                "id": r["id"],
                "brand": r["brand"],
                "display_name": r["display_name"],
                "platform_user_id": r["platform_user_id"],
                "connected": t is not None,
            })
    return out


@router.get("/api/youtube/status")
def youtube_status():
    """Dashboard YouTube panel data: secrets presence, per-account connection
    state, and today's quota usage."""
    return {
        "client_secret_present": yt_oauth.client_secrets_present(),
        "redirect_uri": yt_oauth.redirect_uri(),
        "mock_adapters": os.environ.get("VRWM_MOCK_ADAPTERS") == "1",
        "accounts": _youtube_accounts(),
        "quota": youtube_quota.get_usage(),
    }


@router.get("/api/youtube/quota")
def youtube_quota_status():
    return youtube_quota.get_usage()


@router.get("/api/youtube/auth-url")
def youtube_auth_url(account_id: int = Query(...)):
    """Start YouTube OAuth for one account. Returns the Google consent URL —
    the browser is redirected there and Google sends the user back to
    /api/youtube/callback. Works in mock mode."""
    with dbmod.get_db() as db:
        account = _get_account(db, account_id)
    if account["platform"] != "youtube":
        raise HTTPException(status_code=400, detail="account is not a YouTube account")
    adapter = load_adapter("youtube")
    if adapter is None:
        raise HTTPException(status_code=503, detail="YouTube adapter not installed")
    state, verifier = yt_oauth.create_state(account_id)
    redirect_uri = yt_oauth.redirect_uri()
    try:
        url = adapter.auth_url(redirect_uri, state, code_verifier=verifier)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return {"auth_url": url, "state": state, "redirect_uri": redirect_uri}


_YT_CALLBACK_OK = """<!DOCTYPE html><html><head><meta charset="utf-8">
<title>YouTube connected</title></head>
<body style="font-family:sans-serif;max-width:560px;margin:48px auto;padding:0 16px">
<h1>✅ YouTube connected</h1>
<p><strong>{brand}</strong> ({display}) is now linked to the dashboard.
Channel: <strong>{handle}</strong> (<code>{channel}</code>)</p>
<p>Uploads default to <strong>private</strong> — flip visibility in YouTube Studio.
You can close this tab and go back to the dashboard.</p>
</body></html>"""

_YT_CALLBACK_ERR = """<!DOCTYPE html><html><head><meta charset="utf-8">
<title>YouTube connection failed</title></head>
<body style="font-family:sans-serif;max-width:560px;margin:48px auto;padding:0 16px">
<h1>❌ YouTube connection failed</h1>
<p>{reason}</p>
<p>Close this tab, go back to the dashboard, and try “Connect YouTube” again.</p>
</body></html>"""


@router.get("/api/youtube/callback")
def youtube_callback(code: str = Query(None), state: str = Query(None),
                     error: str = Query(None)):
    """Google redirects here after consent. Exchanges the code, stores the
    encrypted tokens against the state-bound account, and shows a human-
    readable result page (the user is sitting in a browser)."""
    if error:
        return HTMLResponse(_YT_CALLBACK_ERR.format(reason="Google said: " + error),
                            status_code=400)
    if not code or not state:
        return HTMLResponse(_YT_CALLBACK_ERR.format(
            reason="Missing code or state in the callback."), status_code=400)
    account_id, verifier = yt_oauth.consume_state(state)
    if account_id is None:
        return HTMLResponse(_YT_CALLBACK_ERR.format(
            reason="This connect link expired or was already used. "
                   "Start a fresh “Connect YouTube” from the dashboard."),
            status_code=400)
    with dbmod.get_db() as db:
        account = _get_account(db, account_id)
    adapter = load_adapter("youtube")
    if adapter is None:
        return HTMLResponse(_YT_CALLBACK_ERR.format(
            reason="YouTube adapter not installed."), status_code=503)
    try:
        expected_handle = getattr(adapter, "BRAND_CHANNEL_HANDLES", {}).get(
            account["brand"])
        result = adapter.exchange_code(code, yt_oauth.redirect_uri(),
                                       code_verifier=verifier,
                                       expected_handle=expected_handle) or {}
    except Exception as exc:
        log.exception("youtube exchange_code failed for account %s", account_id)
        detail = ("Token exchange failed: %s"
                  "<pre style='text-align:left;background:#f6f6f6;padding:12px;"
                  "overflow:auto'>%s: %s\n\n%s</pre>"
                  % (html.escape(str(exc)), type(exc).__name__,
                     html.escape(str(exc)),
                     html.escape(traceback.format_exc(limit=8))))
        return HTMLResponse(_YT_CALLBACK_ERR.format(reason=detail),
                            status_code=502)
    try:
        tokenstore.store_tokens(account_id, result)
    except Exception as exc:
        return HTMLResponse(_YT_CALLBACK_ERR.format(
            reason="Could not store tokens: %s" % exc), status_code=500)
    channel_id = result.get("platform_user_id")
    try:
        with dbmod.get_db() as db:
            db.execute("UPDATE accounts SET platform_user_id = ? WHERE id = ?",
                       (channel_id, account_id))
            # Never log token values — only metadata.
            _audit(db, None, account_id, "youtube_oauth_complete",
                   {"platform_user_id": channel_id,
                    "scopes": result.get("scopes"),
                    "expires_in": result.get("expires_in")})
    except Exception:
        # Tokens are already stored at this point; a bookkeeping failure must
        # never turn a successful connect into a 500.
        log.exception("youtube callback bookkeeping failed for account %s",
                      account_id)
    return HTMLResponse(_YT_CALLBACK_OK.format(
        brand=account["brand"], display=account["display_name"] or "",
        handle=result.get("channel_handle") or "", channel=channel_id or "unknown"))


@router.post("/api/youtube/disconnect")
def youtube_disconnect(body: dict):
    """Remove stored tokens for a YouTube account (revoke in Google too, via
    https://myaccount.google.com/permissions, to be thorough)."""
    account_id = (body or {}).get("account_id")
    if not account_id:
        raise HTTPException(status_code=400, detail="account_id is required")
    with dbmod.get_db() as db:
        _get_account(db, account_id)
        tokenstore.delete_tokens(account_id)
        _audit(db, None, account_id, "youtube_disconnect", {})
    return {"ok": True, "account_id": account_id}


@router.delete("/api/accounts/{account_id}")
def delete_account(account_id: int):
    """Delete an account row (and its stored tokens). Refuses with 409 while
    the account still has posts — delete those first so history is never
    orphaned."""
    with dbmod.get_db() as db:
        account = _get_account(db, account_id)  # 404 when missing
        n_posts = db.execute(
            "SELECT COUNT(*) FROM posts WHERE account_id = ?",
            (account_id,)).fetchone()[0]
        if n_posts:
            raise HTTPException(
                status_code=409,
                detail=("This account still has %d post(s). "
                        "Delete them first, then delete the account." % n_posts))
        _audit(db, None, account_id, "account_deleted",
               {"brand": account["brand"], "platform": account["platform"],
                "display_name": account["display_name"]})
        db.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
    try:
        tokenstore.delete_tokens(account_id)
    except Exception:
        log.exception("token cleanup failed for deleted account %s", account_id)
    return {"ok": True}


# ---------------------------------------------------------------- health

@router.get("/api/health")
def health():
    return {"ok": True, "mock_adapters": os.environ.get("VRWM_MOCK_ADAPTERS") == "1"}

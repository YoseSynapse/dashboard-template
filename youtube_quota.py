"""YouTube Data API v3 daily quota tracker.

Per YouTube's current docs (upload cost cut Dec 2025; uploads moved
Jun 2026 to their own allowance): each upload costs 1 unit and counts
against a separate 100 uploads/day allowance. The project's standard
10,000 units/day quota is separate and is not consumed at the old
per-upload rate. Usage is keyed by UTC date, so it resets itself at
midnight UTC.

This module only tracks — the adapter checks ``has_capacity()`` before
uploading and calls ``record_upload()`` after a successful upload.
"""

from datetime import datetime, timezone

from . import db as dbmod

UPLOAD_COST_UNITS = 1
DAILY_CAP_UNITS = 10000
DAILY_UPLOAD_ALLOWANCE = 100


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def get_usage() -> dict:
    """Current day's quota usage. Always returns all keys."""
    today = _today()
    with dbmod.get_db() as db:
        row = db.execute(
            "SELECT units_used FROM youtube_quota WHERE date = ?", (today,)
        ).fetchone()
    used = int(row["units_used"]) if row else 0
    # With UPLOAD_COST_UNITS == 1, units_used is also the upload count.
    uploads_today = used // UPLOAD_COST_UNITS if UPLOAD_COST_UNITS else used
    remaining = max(0, DAILY_CAP_UNITS - used)
    uploads_remaining = max(0, DAILY_UPLOAD_ALLOWANCE - uploads_today)
    return {
        "date": today,
        "units_used": used,
        "cap": DAILY_CAP_UNITS,
        "units_remaining": remaining,
        "uploads_today": uploads_today,
        "uploads_remaining": uploads_remaining,
        "upload_allowance": DAILY_UPLOAD_ALLOWANCE,
        "daily_upload_allowance": DAILY_UPLOAD_ALLOWANCE,
        "upload_cost_units": UPLOAD_COST_UNITS,
    }


def has_capacity(cost: int = UPLOAD_COST_UNITS) -> bool:
    """True if one more upload fits in today's 100/day upload allowance."""
    usage = get_usage()
    if cost == UPLOAD_COST_UNITS:
        return usage["uploads_remaining"] >= 1
    return usage["units_remaining"] >= cost


def record_upload(cost: int = UPLOAD_COST_UNITS) -> dict:
    """Add ``cost`` units to today's usage. Returns the updated usage dict."""
    today = _today()
    now = _utcnow_iso()
    with dbmod.get_db() as db:
        db.execute(
            """
            INSERT INTO youtube_quota(date, units_used, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(date) DO UPDATE SET
                units_used = units_used + excluded.units_used,
                updated_at = excluded.updated_at
            """,
            (today, cost, now),
        )
    return get_usage()

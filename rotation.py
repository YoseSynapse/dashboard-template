"""YouTube rotation windows (Jose's rotation, decided 2026-10-12).

Each rotating brand posts 2x/day on a 3-day cycle anchored at Monday
2026-10-12 = cycle day A (cycle index = days since the anchor, mod 3):

    day A: Heist 07:00 + 16:30 - Odds Board 16:30 + 23:30 - FW 07:00 + 23:30
    day B: Heist 16:30 + 23:30 - Odds Board 07:00 + 23:30 - FW 07:00 + 16:30
    day C: Heist 07:00 + 23:30 - Odds Board 07:00 + 16:30 - FW 16:30 + 23:30

All times are America/Los_Angeles wall-clock. MH Outlanders and
jose_personal have no rotation yet and are exempt. Enforcement lives in
``compliance.check_rotation_slot`` and is WARNING-level only — Jose can
always approve anyway.

Timezone note: ``tzdata`` is not in requirements.txt and Windows installs
often have no system tz database, so when ``zoneinfo`` cannot load
America/Los_Angeles this module falls back to the post-2007 US Pacific
DST rules computed by hand (PDT = UTC-7 from the second Sunday of March
10:00 UTC to the first Sunday of November 09:00 UTC, else PST = UTC-8).
"""

from datetime import date, datetime, timedelta, timezone

try:  # Import succeeds even without tz data; construction is what raises.
    from zoneinfo import ZoneInfo

    _PACIFIC = ZoneInfo("America/Los_Angeles")
except Exception:  # pragma: no cover - depends on the host's tz database
    _PACIFIC = None

ANCHOR_DATE = date(2026, 10, 12)  # a Monday — cycle day A
CYCLE_DAYS = ("A", "B", "C")
GRACE_MINUTES = 30

# Window start times ("HH:MM", PT) per cycle day per brand.
ROTATION = {
    "A": {
        "heist": ("07:00", "16:30"),
        "the_odds_board": ("16:30", "23:30"),
        "quiet_position": ("07:00", "23:30"),
    },
    "B": {
        "heist": ("16:30", "23:30"),
        "the_odds_board": ("07:00", "23:30"),
        "quiet_position": ("07:00", "16:30"),
    },
    "C": {
        "heist": ("07:00", "23:30"),
        "the_odds_board": ("07:00", "16:30"),
        "quiet_position": ("16:30", "23:30"),
    },
}
ROTATING_BRANDS = frozenset(ROTATION["A"])


def cycle_day(d: date) -> str:
    """Cycle day letter ("A"/"B"/"C") for a PT calendar date."""
    return CYCLE_DAYS[(d - ANCHOR_DATE).days % 3]


def windows_for(brand: str, d: date) -> list | None:
    """The brand's two window start times ("HH:MM", PT) on date ``d``.

    None when the brand has no rotation (exempt).
    """
    wins = ROTATION[cycle_day(d)].get((brand or "").lower())
    return list(wins) if wins else None


def format_time(hhmm: str) -> str:
    """"07:00" -> "7:00 AM"; "16:30" -> "4:30 PM"; "23:30" -> "11:30 PM"."""
    h, m = (int(p) for p in hhmm.split(":"))
    suffix = "AM" if h < 12 else "PM"
    return f"{h % 12 or 12}:{m:02d} {suffix}"


def parse_scheduled(raw) -> datetime | None:
    """Parse a stored ``scheduled_at`` into an aware datetime.

    Stored values are UTC ISO (compose sends ``Date.toISOString()``);
    a naive value is assumed UTC, matching the scheduler's comparison.
    Returns None for empty/unparseable input.
    """
    if not raw:
        return None
    s = str(raw).strip()
    if not s:
        return None
    if s.endswith(("Z", "z")):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """Date of the n-th ``weekday`` (Mon=0 .. Sun=6) of a month."""
    first = date(year, month, 1)
    delta = (weekday - first.weekday()) % 7
    return first + timedelta(days=delta + 7 * (n - 1))


def _fallback_offset_hours(dt_utc: datetime) -> int:
    """US Pacific UTC offset (-7 PDT / -8 PST) from the post-2007 DST rules.

    PDT runs from the second Sunday of March 02:00 PST (= 10:00 UTC) to
    the first Sunday of November 02:00 PDT (= 09:00 UTC).
    """
    y = dt_utc.year
    start = datetime(y, 3, _nth_weekday(y, 3, 6, 2).day, 10, tzinfo=timezone.utc)
    end = datetime(y, 11, _nth_weekday(y, 11, 6, 1).day, 9, tzinfo=timezone.utc)
    return -7 if start <= dt_utc < end else -8


def to_pacific(dt: datetime) -> datetime:
    """Convert an aware datetime to America/Los_Angeles local time."""
    if _PACIFIC is not None:
        return dt.astimezone(_PACIFIC)
    offset = timezone(timedelta(hours=_fallback_offset_hours(dt)))
    return dt.astimezone(offset)


def check_slot(brand: str, scheduled_at) -> dict | None:
    """Evaluate a scheduled time against the brand's rotation windows.

    Returns None when the brand is exempt, the post is unscheduled or
    unparseable, or the PT time falls within +/-GRACE_MINUTES of one of
    that PT date's two windows. Otherwise returns a dict with the PT
    datetime, the cycle day, and the correct windows for the message.
    """
    dt = parse_scheduled(scheduled_at)
    if dt is None:
        return None
    pt = to_pacific(dt)
    wins = windows_for(brand, pt.date())
    if wins is None:
        return None
    minutes = pt.hour * 60 + pt.minute
    for w in wins:
        wh, wm = (int(p) for p in w.split(":"))
        if abs(minutes - (wh * 60 + wm)) <= GRACE_MINUTES:
            return None
    return {"pt": pt, "cycle_day": cycle_day(pt.date()), "windows": wins}

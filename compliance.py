"""Brand compliance engine.

``check_post(brand, title, caption, hashtags)`` implements the exact brand
rules from the integration contract. Matching is case-insensitive substring
matching over title + caption + hashtags.

Each returned item is {"rule": str, "message": str}.

Note: the Heist concept/fan-art label rule depends on the post's
``labels_concept_art`` flag, which is not part of the contract's
``check_post`` signature — it is applied in the submit/detail routes
(``heist_label_warning``) where the stored flag is available.
"""

import re

try:  # Rotation windows live in app/rotation.py (Patch Pack #3).
    from . import rotation as _rotation
except Exception:  # pragma: no cover - defensive, mirrors scheduler imports
    _rotation = None

# --- Quiet Position: no binary/broker/affiliate content (highest-risk item) ---
_QP_BLOCKS = [
    "pocket option",
    "quotex",
    "iq option",
    "binomo",
    "olymp trade",
    "olymptrade",
    "exnova",
    "deriv.com",
    "deposit bonus",
    "affiliate link",
    "sign up with my link",
    "broker",
    "binary option",
    "trading signal",
    "option signal",
    "copy trade",
    "copytrade",
]
_QP_WARNS = [
    "guaranteed",
    "get rich",
    "100% win",
    "risk-free",
    "can't lose",
]

# --- The Odds Board: zero gambling-operator links / bonuses / deposit CTAs ---
_OB_BLOCKS = [
    "draftkings",
    "fanduel",
    "bet365",
    "caesars",
    "betmgm",
    "pointsbet",
    "unibet",
    "william hill",
    "ladbrokes",
    "paddy power",
    "promo code",
    "free bet",
    "deposit bonus",
    "oddsportal",
    "sportsbook",
    "betting site",
    "online casino",
    "casino bonus",
    "place your bet",
    "bet now",
]
_OB_WARNS = [
    "lock of the",
    "guaranteed",
    "can't lose",
]

_BLOCK_FINGERPRINTS = {
    "quiet_position": _QP_BLOCKS,
    "the_odds_board": _OB_BLOCKS,
    "heist": [],
    "jose_personal": [],
    "mh_outlanders": [],
}

_WARN_FINGERPRINTS = {
    "quiet_position": _QP_WARNS,
    "the_odds_board": _OB_WARNS,
    "heist": [],
    "jose_personal": [],
    "mh_outlanders": [],
}

# All brands: warn on unqualified financial-advice language.
_ALL_BRAND_WARNS = ["financial advice"]

# Required disclaimer forms: when the text carries the negation, the
# all_brands_warn rule PASSES instead of warning. Covers (case-insensitive,
# hyphens treated as spaces):
#   "not financial advice"
#   "not betting or financial advice"
#   "not-financial-advice"
_FINANCIAL_ADVICE_DISCLAIMERS = [
    "not financial advice",
    "not betting or financial advice",
]


def _has_financial_advice_disclaimer(hay: str) -> bool:
    normalized = " ".join(hay.lower().replace("-", " ").replace("_", " ").split())
    return any(form in normalized for form in _FINANCIAL_ADVICE_DISCLAIMERS)


def _haystack(title, caption, hashtags) -> str:
    parts = [title or "", caption or ""]
    parts.extend(hashtags or [])
    return " ".join(str(p) for p in parts).lower()


# --- Unfilled template placeholders (all brands) ---
# Bracketed tokens like [topic] / [unexpected fact] are kit scaffolding that
# must be replaced with real copy before a post can ship (an unfilled
# "[unexpected fact] about [topic]" tail shipped in OB-04's caption).
# [CONCEPT] and [RUMOR] are NOT placeholders — they are the required labels
# on Heist content — so they are allowlisted. "[Links — to be added]" IS a
# placeholder: the real link block must replace it.
_PLACEHOLDER_RE = re.compile(r"\[([^\[\]\n]{1,80})\]")
_PLACEHOLDER_ALLOWLIST = {"concept", "rumor"}


def find_placeholders(title, caption, hashtags) -> list:
    """Bracketed template tokens still unfilled, in original case, de-duped."""
    parts = [title or "", caption or ""]
    parts.extend(str(h) for h in (hashtags or []))
    found: list = []
    seen: set = set()
    for m in _PLACEHOLDER_RE.finditer(" ".join(parts)):
        token = m.group(1).strip()
        if token.lower() in _PLACEHOLDER_ALLOWLIST or token.lower() in seen:
            continue
        seen.add(token.lower())
        found.append(m.group(0))
    return found


def check_post(brand: str, title: str, caption: str, hashtags: list) -> dict:
    """Run brand rules. Returns {"blocks": [...], "warnings": [...]}."""
    brand = (brand or "").lower()
    hay = _haystack(title, caption, hashtags)
    blocks: list = []
    warnings: list = []

    for tok in find_placeholders(title, caption, hashtags):
        blocks.append(
            {
                "rule": "unfilled_placeholder",
                "message": (
                    f"Unfilled template placeholder '{tok}' — replace it with "
                    "real copy; a post cannot be approved while it remains."
                ),
            }
        )

    for phrase in _BLOCK_FINGERPRINTS.get(brand, []):
        if phrase in hay:
            blocks.append(
                {
                    "rule": f"{brand}_block",
                    "message": (
                        f"Blocked phrase '{phrase}' detected — "
                        f"{brand.replace('_', ' ').title()} may not carry this content."
                    ),
                }
            )

    for phrase in _WARN_FINGERPRINTS.get(brand, []):
        if phrase in hay:
            warnings.append(
                {
                    "rule": f"{brand}_warn",
                    "message": (
                        f"Risky phrase '{phrase}' detected — review before approving."
                    ),
                }
            )

    for phrase in _ALL_BRAND_WARNS:
        if phrase in hay:
            # Disclaimer present (e.g. "Education only — not betting or
            # financial advice.") — the required negation makes this pass.
            if phrase == "financial advice" and _has_financial_advice_disclaimer(hay):
                continue
            warnings.append(
                {
                    "rule": "all_brands_warn",
                    "message": (
                        "Contains 'financial advice' language — add a not-financial-advice "
                        "disclaimer or rephrase as education."
                    ),
                }
            )

    return {"blocks": blocks, "warnings": warnings}


def check_hashtag_limits(platform: str, hashtags: list) -> dict:
    """Platform hashtag limits. TikTok: >100 hashtags BLOCKS. X: >4 WARNS."""
    platform = (platform or "").lower()
    n = len(hashtags or [])
    blocks: list = []
    warnings: list = []
    if platform == "tiktok" and n > 100:
        blocks.append(
            {
                "rule": "tiktok_hashtag_limit",
                "message": f"TikTok allows at most 100 hashtags — this post has {n}.",
            }
        )
    if platform == "x" and n > 4:
        warnings.append(
            {
                "rule": "x_hashtag_limit",
                "message": (
                    f"X recommends at most 4 hashtags — this post has {n}. "
                    "Consider trimming to avoid automation-throttling signals."
                ),
            }
        )
    return {"blocks": blocks, "warnings": warnings}


def heist_label_warning(labels_concept_art: bool) -> dict | None:
    """Heist rule: concept/fan art must be labeled. Returns a warning item
    unless the post's labels_concept_art flag is true, else None."""
    if labels_concept_art:
        return None
    return {
        "rule": "heist_concept_art_label",
        "message": "Heist posts must label concept/fan art — tick the label checkbox.",
    }


def check_rotation_slot(platform: str, brand: str, scheduled_at) -> dict | None:
    """YouTube rotation rule (Jose, 2026-10-12): rotating brands post in two
    daily PT windows on a 3-day cycle (see app/rotation.py). Returns a
    WARNING item when a YouTube post's scheduled PT time falls outside
    that date's windows (+/-30 min grace), else None. Warning only —
    never a block; Jose can approve anyway. Exempt: non-YouTube posts,
    unscheduled posts, and brands with no rotation (MH, personal)."""
    if _rotation is None or (platform or "").lower() != "youtube":
        return None
    info = _rotation.check_slot(brand, scheduled_at)
    if info is None:
        return None
    pt = info["pt"]
    wins = " and ".join(_rotation.format_time(w) for w in info["windows"])
    brand_name = (brand or "").replace("_", " ").title()
    pt_time = pt.strftime("%I:%M %p").lstrip("0")
    pt_day = pt.strftime("%a, %b ") + str(pt.day)
    return {
        "rule": "youtube_rotation_slot",
        "message": (
            f"Scheduled {pt_time} PT on {pt_day} is outside {brand_name}'s "
            f"YouTube rotation windows for cycle day {info['cycle_day']} "
            f"({wins} PT, ±{_rotation.GRACE_MINUTES} min grace). Reschedule "
            "into a window — or approve anyway; this is a warning, not a block."
        ),
    }

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


def check_post(brand: str, title: str, caption: str, hashtags: list) -> dict:
    """Run brand rules. Returns {"blocks": [...], "warnings": [...]}."""
    brand = (brand or "").lower()
    hay = _haystack(title, caption, hashtags)
    blocks: list = []
    warnings: list = []

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

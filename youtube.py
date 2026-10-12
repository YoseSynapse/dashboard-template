"""YouTube Data API v3 adapter.

Real flow (google-api-python-client + google-auth-oauthlib; no live calls
unless the user finished OAuth and VRWM_MOCK_ADAPTERS is unset):

  OAuth: Desktop-app (installed) flow. client_secret.json must sit in the
    phase2 folder (loaded at runtime via app.yt_oauth — never shipped, never
    logged). Scope: https://www.googleapis.com/auth/youtube.upload.
    platform_user_id = the channel id (channels.list mine=true).
    Note: while the OAuth consent screen is in Testing mode, tokens die
    ~7 days; move it to Production (Jose's call).
  Publish: videos.insert (resumable upload via MediaFileUpload).
    privacyStatus defaults to "private" — nothing goes public accidentally;
    the user flips visibility in YouTube Studio.

Scheduling (native): when post["scheduled_at"] is set, status =
  {"privacyStatus": "private", "publishAt": "<RFC3339 UTC>"}.
  publishAt is NEVER paired with "public" (YouTube silently ignores it).

Validations (active in BOTH mock and real mode): title <= 100 chars,
description <= 5000 chars. scheduled_at is normalized to RFC3339 UTC
(naive ISO strings are assumed UTC -- documented).

Quota: videos.insert costs 1600 units against a 10,000/day testing cap.
The adapter refuses when today has no room and records usage on success.
"""

import datetime
import json
import os
import secrets

from adapters.base import BaseAdapter

_SCOPES = ["https://www.googleapis.com/auth/youtube.upload",
           "https://www.googleapis.com/auth/youtube.readonly"]
_TITLE_LIMIT = 100
_DESCRIPTION_LIMIT = 5000
_CHUNK_MB = 8  # 8 MB chunks; must be a multiple of 256 KB


class AdapterError(Exception):
    """Raised for OAuth/token/config failures (exchange_code / refresh)."""


def _mock():
    return os.environ.get("VRWM_MOCK_ADAPTERS") == "1"


def _fail(message):
    return {"ok": False, "platform_post_id": None, "error": message, "cost_usd": 0.0}


def _to_rfc3339_utc(value):
    """Normalize an ISO-8601 scheduled_at to RFC3339 UTC (...Z).

    Naive datetimes are assumed to already be UTC -- the composer should send
    an offset or 'Z'; this is documented rather than guessed.
    """
    s = (value or "").strip()
    if not s:
        raise AdapterError("scheduled_at is empty; cannot schedule.")
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        dt = datetime.datetime.fromisoformat(s)
    except ValueError:
        raise AdapterError("scheduled_at is not valid ISO-8601: %r" % (value,))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _default_client_factory(credentials):
    """Build the real YouTube Data API v3 client."""
    from googleapiclient.discovery import build
    return build("youtube", "v3", credentials=credentials, cache_discovery=False)


class YouTubeAdapter(BaseAdapter):
    platform = "youtube"

    # Canonical YouTube handle per dashboard brand slug. When one Google
    # account owns several channels, the connect flow matches the brand's
    # handle instead of blindly taking channels.list's first item.
    BRAND_CHANNEL_HANDLES = {
        "heist": "@Heisthq365official",
        "the_odds_board": "@OddsBoard",
        "quiet_position": "@facelesswicksofficial",
    }

    def __init__(self, client_factory=None):
        # client_factory(credentials) -> service with .channels().list(),
        # .videos().insert(). Injected in tests to stub the YouTube API.
        self._client_factory = client_factory or _default_client_factory

    # ------------------------------------------------------------ internals
    def _secrets_file(self) -> str:
        if _mock():
            return "mock"
        # Local import: routes/scheduler import the adapter at module load,
        # and app.yt_oauth lives in the app package — keep the import lazy so
        # the adapters package stays importable standalone.
        from app import yt_oauth
        p = yt_oauth.client_secrets_path()
        if not p.is_file() or p.stat().st_size == 0:
            raise AdapterError(
                "client_secret.json is missing from the phase2 folder — "
                "drop it in next to run.bat, then reconnect. "
                "See WINDOWS_SETUP.md ('Connect YouTube')."
            )
        return str(p)

    def _redirect_uri(self) -> str:
        from app import yt_oauth
        return yt_oauth.redirect_uri()

    def _flow(self, redirect_uri: str, code_verifier: str | None = None):
        from google_auth_oauthlib.flow import InstalledAppFlow
        kwargs: dict = {}
        if code_verifier:
            # Use OUR verifier for both authorization_url() and fetch_token().
            # InstalledAppFlow auto-generates a fresh verifier per instance;
            # two separate instances (auth-url vs callback) would mismatch and
            # Google rejects the exchange with "Missing code verifier".
            kwargs["code_verifier"] = code_verifier
        else:
            # No verifier anywhere: disable auto-generation so no
            # code_challenge is sent either (keeps the pair consistent).
            kwargs["autogenerate_code_verifier"] = False
        return InstalledAppFlow.from_client_secrets_file(
            self._secrets_file(), scopes=_SCOPES, redirect_uri=redirect_uri,
            **kwargs
        )

    def _channel_id(self, service, expected_handle=None):
        """Return (channel_id, handle_label). When the Google account owns
        several channels and expected_handle is given, pick the channel whose
        custom URL matches; raise instead of silently linking the wrong one."""
        resp = service.channels().list(part="id,snippet", mine=True).execute()
        items = resp.get("items", []) if isinstance(resp, dict) else []
        if not items:
            raise AdapterError("YouTube channels.list (mine=true) returned no channel.")
        if expected_handle and len(items) > 1:
            want = expected_handle.strip().lower().lstrip("@")
            for it in items:
                snip = it.get("snippet") or {}
                custom = (snip.get("customUrl") or "").strip().lower().lstrip("@")
                title = (snip.get("title") or "").strip().lower()
                if custom == want or title == want:
                    return it["id"], snip.get("customUrl") or snip.get("title") or it["id"]
            found = ", ".join(
                (it.get("snippet") or {}).get("customUrl")
                or (it.get("snippet") or {}).get("title")
                or it.get("id", "?")
                for it in items
            )
            raise AdapterError(
                "This Google account owns several YouTube channels (%s) but none "
                "matches the expected %s. Open YouTube's account switcher, make "
                "sure the right channel exists, then retry." % (found, expected_handle)
            )
        first = items[0]
        if not first.get("id"):
            raise AdapterError("YouTube channels.list (mine=true) returned no channel.")
        snip = first.get("snippet") or {}
        return first["id"], snip.get("customUrl") or snip.get("title") or first["id"]

    def _credentials(self, token: str):
        from google.oauth2.credentials import Credentials
        return Credentials(token=token, scopes=_SCOPES)

    # ------------------------------------------------------------------ OAuth
    def auth_url(self, redirect_uri: str, state: str,
                 code_verifier: str | None = None) -> str:
        if _mock():
            return ("https://mock.vrwm.local/youtube/oauth/authorize"
                    "?response_type=code&state=%s&mock=1" % state)
        flow = self._flow(redirect_uri, code_verifier)
        url, _ = flow.authorization_url(
            access_type="offline",  # refresh token for the scheduler daemon
            prompt="consent",       # force refresh_token issuance on reconnect
            state=state,
        )
        return url

    def exchange_code(self, code: str, redirect_uri: str,
                      code_verifier: str | None = None,
                      expected_handle: str | None = None) -> dict:
        if _mock():
            return {
                "access_token": "mock_youtube_access_" + secrets.token_hex(8),
                "refresh_token": "mock_youtube_refresh_" + secrets.token_hex(8),
                "expires_in": 3600,
                "platform_user_id": "mock_user_youtube",
                "scopes": " ".join(_SCOPES),
            }
        flow = self._flow(redirect_uri, code_verifier)
        try:
            flow.fetch_token(code=code)
        except Exception as exc:
            raise AdapterError("YouTube token exchange failed: %s" % exc)
        creds = flow.credentials
        service = self._client_factory(creds)
        channel_id, handle_label = self._channel_id(service, expected_handle)
        return {
            "access_token": creds.token,
            "refresh_token": creds.refresh_token,
            "expires_in": 3600,  # Google access tokens live ~1 hour
            "platform_user_id": channel_id,
            "channel_handle": handle_label,
            "scopes": " ".join(_SCOPES),
        }

    def refresh(self, refresh_token: str) -> dict:
        if _mock():
            return {
                "access_token": "mock_youtube_access_" + secrets.token_hex(8),
                "refresh_token": "mock_youtube_refresh_" + secrets.token_hex(8),
                "expires_in": 3600,
                "platform_user_id": "mock_user_youtube",
                "scopes": " ".join(_SCOPES),
            }
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        secrets_file = self._secrets_file()
        with open(secrets_file, encoding="utf-8") as fh:
            client_cfg = json.load(fh)
        # Desktop ("installed") secrets may nest under "installed" or "web".
        cfg = client_cfg.get("installed") or client_cfg.get("web") or {}
        creds = Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri=cfg.get("token_uri", "https://oauth2.googleapis.com/token"),
            client_id=cfg.get("client_id"),
            client_secret=cfg.get("client_secret"),
            scopes=_SCOPES,
        )
        try:
            creds.refresh(Request())
        except Exception as exc:
            raise AdapterError("YouTube token refresh failed: %s" % exc)
        service = self._client_factory(creds)
        channel_id, _handle_label = self._channel_id(service)
        return {
            "access_token": creds.token,
            # Google often doesn't rotate the refresh token; keep the old one.
            "refresh_token": creds.refresh_token or refresh_token,
            "expires_in": 3600,
            "platform_user_id": channel_id,
            "scopes": " ".join(_SCOPES),
        }

    # ---------------------------------------------------------------- publish
    def _compose_description(self, post):
        caption = (post.get("caption") or "").strip()
        tags = ["#" + h.lstrip("#").strip() for h in (post.get("hashtags") or []) if h and h.strip()]
        if tags:
            return (caption + "\n\n" + " ".join(tags)).strip()
        return caption

    def _validate(self, post):
        title = (post.get("title") or "").strip()
        if not title:
            return "YouTube publish needs post['title'] (used as the video title)."
        if len(title) > _TITLE_LIMIT:
            return ("YouTube title is %d chars; limit is %d."
                    % (len(title), _TITLE_LIMIT))
        description = self._compose_description(post)
        if len(description) > _DESCRIPTION_LIMIT:
            return ("YouTube description is %d chars; limit is %d."
                    % (len(description), _DESCRIPTION_LIMIT))
        scheduled_at = post.get("scheduled_at")
        if scheduled_at:
            try:
                _to_rfc3339_utc(scheduled_at)
            except AdapterError as exc:
                return str(exc)
        return None

    def publish(self, post: dict, media_path: str) -> dict:
        # Title/description/scheduled_at validations stay ACTIVE in mock mode.
        err = self._validate(post)
        if err:
            return _fail(err)
        if _mock():
            return {
                "ok": True,
                "platform_post_id": "mock_youtube_%s" % secrets.token_hex(4),
                "error": None,
                "cost_usd": self.estimate_cost_usd(post),
            }
        account = post.get("account") or {}
        token = account.get("access_token")
        if not token:
            return _fail("No access token: post['account']['access_token'] is missing; "
                         "the scheduler must inject the decrypted token before publish().")
        if not media_path or not os.path.isfile(media_path):
            return _fail("YouTube publish needs a local video file; media_path is "
                         "missing or not a file: %r" % (media_path,))
        from app import youtube_quota
        if not youtube_quota.has_capacity():
            return _fail("YouTube daily quota is exhausted "
                         "(%d units/day; uploads cost %d). Try again tomorrow."
                         % (youtube_quota.DAILY_CAP_UNITS,
                            youtube_quota.UPLOAD_COST_UNITS))
        try:
            result = self._publish_real(token, post, media_path)
        except Exception as exc:
            return _fail("YouTube API error: %s" % exc)
        if result.get("ok"):
            youtube_quota.record_upload()
        return result

    def _publish_real(self, token, post, media_path):
        from googleapiclient.http import MediaFileUpload

        title = (post.get("title") or "").strip()
        description = self._compose_description(post)
        scheduled_at = post.get("scheduled_at")

        # Native scheduling: publishAt is ONLY ever paired with private.
        # YouTube silently ignores publishAt + public, so we never emit that.
        # Default privacyStatus is "private" — nothing goes public accidentally.
        status = {"privacyStatus": "private"}
        if scheduled_at:
            status["publishAt"] = _to_rfc3339_utc(scheduled_at)

        size = os.path.getsize(media_path)
        if size <= 0:
            return _fail("Media file is empty: %s" % media_path)

        body = {
            "snippet": {"title": title, "description": description},
            "status": status,
        }
        media = MediaFileUpload(media_path, chunksize=_CHUNK_MB * 1024 * 1024,
                                resumable=True)
        service = self._client_factory(self._credentials(token))
        request = service.videos().insert(
            part="snippet,status", body=body, media_body=media)

        response = None
        while response is None:
            try:
                _, response = request.next_chunk()
            except Exception as exc:
                return _fail("YouTube resumable upload failed: %s" % exc)

        video_id = response.get("id") if isinstance(response, dict) else None
        if not video_id:
            return _fail("YouTube upload finished without returning a video id.")
        return {"ok": True, "platform_post_id": video_id, "error": None,
                "cost_usd": self.estimate_cost_usd(post)}

    def supports_native_scheduling(self) -> bool:
        return True

    def estimate_cost_usd(self, post: dict) -> float:
        return 0.0

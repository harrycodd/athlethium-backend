"""
Strava Integration Service.

OAuth flow (CSRF-safe):
  1. The signed-in app calls `start_authorization`, which stores a single-use, short-lived
     state nonce in `oauthStates/{nonce}` bound to the caller's uid and a validated return URL.
  2. Strava redirects to `strava_callback` with that nonce; `complete_authorization` consumes it,
     exchanges the code and stores tokens server-side only in `users/{uid}/private/strava`.
The user document only ever carries `stravaConnected` and `stravaAthleteId`.
"""

import secrets
import time
import urllib.parse
from typing import Any, Dict, Optional, Tuple

try:
    import requests
except ImportError:
    requests = None
try:
    from firebase_admin import firestore
except ImportError:
    firestore = None


STRAVA_TOKEN_URL = "https://www.strava.com/oauth/token"
STRAVA_DEAUTHORIZE_URL = "https://www.strava.com/oauth/deauthorize"
STRAVA_AUTHORIZE_URL = "https://www.strava.com/oauth/mobile/authorize"
STRAVA_SCOPE = "activity:read_all,profile:read_all"
HTTP_TIMEOUT_SEC = 10
STATE_TTL_SEC = 600

# Only the app's own deep-link schemes may receive the post-OAuth redirect (no open redirect).
ALLOWED_RETURN_SCHEMES = {"athlethium", "exp", "exps"}
DEFAULT_RETURN_URL = "athlethium://settings"

LEGACY_TOKEN_FIELDS = ["stravaAccessToken", "stravaRefreshToken", "stravaExpiresAt"]


class StravaError(Exception):
    """A Strava API failure, with a short machine-readable code safe to show the app."""

    def __init__(self, code: str, detail: str = ""):
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code


def is_allowed_return_url(url: Any) -> bool:
    if not isinstance(url, str) or not url or len(url) > 512:
        return False
    return urllib.parse.urlsplit(url).scheme.lower() in ALLOWED_RETURN_SCHEMES


def with_query(url: str, **params: str) -> str:
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}{urllib.parse.urlencode(params)}"


def private_token_ref(db, user_id: str):
    return db.collection("users").document(user_id).collection("private").document("strava")


class StravaService:
    """Manages Strava OAuth and token storage."""

    @classmethod
    def start_authorization(
        cls, user_id: str, return_url: Optional[str], client_id: str, redirect_uri: str
    ) -> Dict[str, str]:
        if return_url is None:
            return_url = DEFAULT_RETURN_URL
        if not is_allowed_return_url(return_url):
            raise ValueError("returnUrl must use the app's own URL scheme")

        state = secrets.token_urlsafe(24)
        firestore.client().collection("oauthStates").document(state).set({
            "uid": user_id,
            "provider": "strava",
            "returnUrl": return_url,
            "expiresAt": int(time.time()) + STATE_TTL_SEC,
        })
        auth_url = f"{STRAVA_AUTHORIZE_URL}?" + urllib.parse.urlencode({
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "approval_prompt": "auto",
            "scope": STRAVA_SCOPE,
            "state": state,
        })
        return {"state": state, "authUrl": auth_url, "returnUrl": return_url}

    @classmethod
    def consume_state(cls, state: Optional[str]) -> Optional[Dict[str, Any]]:
        """Atomically reads and deletes a state nonce. Returns None if unknown or expired."""
        if not state or not isinstance(state, str) or len(state) > 128 or "/" in state:
            return None
        db = firestore.client()
        ref = db.collection("oauthStates").document(state)

        @firestore.transactional
        def _consume(tx):
            snap = ref.get(transaction=tx)
            if not snap.exists:
                return None
            tx.delete(ref)
            return snap.to_dict()

        data = _consume(db.transaction())
        if not data or data.get("provider") != "strava":
            return None
        if int(data.get("expiresAt", 0)) < time.time():
            return None
        return data

    @classmethod
    def exchange_oauth_code(cls, code: str, user_id: str, client_id: str, client_secret: str) -> Dict[str, Any]:
        """Exchanges the auth code for tokens and stores them server-side. Raises StravaError."""
        if not code:
            raise StravaError("missing_code")
        token_data = cls._post_token({
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "grant_type": "authorization_code",
        })
        if not token_data.get("access_token") or not token_data.get("refresh_token"):
            raise StravaError("strava_bad_response", "token payload incomplete")

        athlete_id = (token_data.get("athlete") or {}).get("id")
        db = firestore.client()
        private_token_ref(db, user_id).set({
            "accessToken": token_data["access_token"],
            "refreshToken": token_data["refresh_token"],
            "expiresAt": token_data.get("expires_at"),
            "athleteId": str(athlete_id) if athlete_id is not None else None,
            "updatedAt": firestore.SERVER_TIMESTAMP,
        })
        user_update = {
            "stravaConnected": True,
            "stravaAthleteId": str(athlete_id) if athlete_id is not None else None,
        }
        user_update.update({f: firestore.DELETE_FIELD for f in LEGACY_TOKEN_FIELDS})
        db.collection("users").document(user_id).set(user_update, merge=True)
        return {"success": True, "athleteId": athlete_id}

    @classmethod
    def disconnect(cls, user_id: str) -> Dict[str, Any]:
        """Revokes the Strava grant (best effort) and removes all stored tokens."""
        db = firestore.client()
        ref = private_token_ref(db, user_id)
        snap = ref.get()
        revoked = False
        if snap.exists:
            access_token = (snap.to_dict() or {}).get("accessToken")
            if access_token:
                try:
                    resp = requests.post(
                        STRAVA_DEAUTHORIZE_URL, data={"access_token": access_token}, timeout=HTTP_TIMEOUT_SEC
                    )
                    revoked = resp.ok
                except requests.RequestException as exc:
                    print(f"[StravaService] Deauthorize failed for {user_id}: {exc}")
            ref.delete()

        user_update = {"stravaConnected": False, "stravaAthleteId": firestore.DELETE_FIELD}
        user_update.update({f: firestore.DELETE_FIELD for f in LEGACY_TOKEN_FIELDS})
        db.collection("users").document(user_id).set(user_update, merge=True)
        return {"success": True, "revoked": revoked}

    @staticmethod
    def _post_token(payload: Dict[str, Any]) -> Dict[str, Any]:
        try:
            resp = requests.post(STRAVA_TOKEN_URL, data=payload, timeout=HTTP_TIMEOUT_SEC)
        except requests.Timeout as exc:
            raise StravaError("strava_timeout") from exc
        except requests.RequestException as exc:
            raise StravaError("strava_unreachable") from exc

        if resp.status_code == 429:
            raise StravaError("strava_rate_limited")
        if resp.status_code in (400, 401, 403):
            raise StravaError("strava_auth_rejected", f"HTTP {resp.status_code}")
        if not resp.ok:
            raise StravaError("strava_unavailable", f"HTTP {resp.status_code}")
        try:
            body = resp.json()
        except ValueError as exc:
            raise StravaError("strava_bad_response", "non-JSON body") from exc
        if not isinstance(body, dict):
            raise StravaError("strava_bad_response", "unexpected JSON shape")
        return body


def complete_authorization(
    state: Optional[str], code: Optional[str], error: Optional[str], client_id: str, client_secret: str
) -> Tuple[int, Dict[str, str]]:
    """
    Handles the OAuth redirect. Returns (status, headers) for the HTTP response.
    Unknown/expired state -> 400 with no redirect (the return URL can't be trusted).
    """
    state_data = StravaService.consume_state(state)
    if state_data is None:
        return 400, {}
    return_url = state_data.get("returnUrl") or DEFAULT_RETURN_URL
    if not is_allowed_return_url(return_url):  # defence in depth; validated at creation too
        return_url = DEFAULT_RETURN_URL

    if error:
        return 302, {"Location": with_query(return_url, error="access_denied")}
    try:
        StravaService.exchange_oauth_code(code, state_data["uid"], client_id, client_secret)
    except StravaError as exc:
        print(f"[StravaService] Token exchange failed for {state_data['uid']}: {exc}")
        return 302, {"Location": with_query(return_url, error=exc.code)}
    return 302, {"Location": with_query(return_url, success="true")}

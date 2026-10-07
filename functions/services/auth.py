"""
Request authentication.

Every app-facing endpoint requires a Firebase ID token in `Authorization: Bearer <token>`.
The caller's uid always comes from the verified token, never from the request body.
"""

from typing import Any, Optional

try:
    from firebase_admin import auth as firebase_auth
except ImportError:
    firebase_auth = None


class AuthError(Exception):
    """Raised when a request has no valid Firebase ID token."""


def require_uid(req: Any) -> str:
    """Returns the verified uid for the request, or raises AuthError."""
    header = req.headers.get("Authorization", "") if req is not None else ""
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token.strip():
        raise AuthError("Missing bearer token")
    try:
        decoded = firebase_auth.verify_id_token(token.strip())
    except Exception as exc:
        raise AuthError("Invalid or expired ID token") from exc
    uid: Optional[str] = decoded.get("uid")
    if not uid:
        raise AuthError("Token has no uid")
    return uid

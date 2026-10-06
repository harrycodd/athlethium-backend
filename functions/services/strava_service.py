"""
Strava Integration Service.
Handles Strava OAuth exchange and activity webhook events.
"""

import os
import json
try:
    import requests
except ImportError:
    requests = None
from typing import Dict, Any, Optional
try:
    from firebase_admin import firestore
except ImportError:
    firestore = None



class StravaService:
    """
    Manages Strava OAuth and Webhook ingestion.
    """

    @classmethod
    def exchange_oauth_code(
        cls,
        code: str,
        user_id: str,
        client_id: str,
        client_secret: str
    ) -> Dict[str, Any]:
        """
        Exchanges temporary auth code for permanent refresh/access tokens and stores in Firestore.
        """
        resp = requests.post("https://www.strava.com/oauth/token", data={
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "grant_type": "authorization_code"
        })

        if not resp.ok:
            return {"error": f"Strava token exchange failed: {resp.text}"}

        token_data = resp.json()
        db = firestore.client()
        db.collection("users").document(user_id).set({
            "stravaConnected": True,
            "stravaAccessToken": token_data.get("access_token"),
            "stravaRefreshToken": token_data.get("refresh_token"),
            "stravaExpiresAt": token_data.get("expires_at"),
            "stravaAthleteId": str(token_data.get("athlete", {}).get("id"))
        }, merge=True)

        return {"success": True, "athleteId": token_data.get("athlete", {}).get("id")}

"""
Manage the Strava push subscription that delivers activity events to the `strava_webhook` function.

Strava allows one subscription per API application. Creating it makes Strava call the deployed
`strava_webhook` with the verify token, so deploy the functions and set the STRAVA_VERIFY_TOKEN
secret first. Secrets are read from the environment (or prompted for), never from this file.

    export STRAVA_CLIENT_SECRET=...        # from https://www.strava.com/settings/api
    export STRAVA_VERIFY_TOKEN=...         # the same value as the STRAVA_VERIFY_TOKEN function secret
    python scripts/strava_webhook_subscription.py show
    python scripts/strava_webhook_subscription.py create
    python scripts/strava_webhook_subscription.py delete --id 12345

This talks to Strava's API only; it never touches Firebase.
"""

import argparse
import getpass
import json
import os
import sys

import requests

SUBSCRIPTIONS_URL = "https://www.strava.com/api/v3/push_subscriptions"
DEFAULT_CLIENT_ID = "157155"  # public OAuth client id
DEFAULT_CALLBACK = "https://europe-west2-athlethium-app.cloudfunctions.net/strava_webhook"
TIMEOUT_SEC = 30


def _secret(name: str, prompt: str) -> str:
    value = os.environ.get(name) or getpass.getpass(f"{prompt}: ").strip()
    if not value:
        sys.exit(f"{name} is required")
    return value


def show(client_id: str, client_secret: str) -> list:
    resp = requests.get(SUBSCRIPTIONS_URL, params={"client_id": client_id, "client_secret": client_secret},
                        timeout=TIMEOUT_SEC)
    if not resp.ok:
        sys.exit(f"Could not list subscriptions (HTTP {resp.status_code}): {resp.text}")
    subs = resp.json()
    print(json.dumps(subs, indent=2) if subs else "No subscription.")
    return subs


def create(client_id: str, client_secret: str, callback_url: str, verify_token: str) -> None:
    print(f"Creating subscription for {callback_url} (Strava will call it to verify)...")
    resp = requests.post(SUBSCRIPTIONS_URL, timeout=TIMEOUT_SEC, data={
        "client_id": client_id, "client_secret": client_secret,
        "callback_url": callback_url, "verify_token": verify_token,
    })
    if not resp.ok:
        sys.exit(f"Strava refused the subscription (HTTP {resp.status_code}): {resp.text}\n"
                 "Check the function is deployed, STRAVA_VERIFY_TOKEN matches the function secret, and no "
                 "subscription exists already (`show`).")
    sub_id = resp.json().get("id")
    print(f"Subscribed. Subscription id: {sub_id}")
    print("Optional hardening: put STRAVA_SUBSCRIPTION_ID=<id> in functions/.env.athlethium-app and redeploy, "
          "so events for any other subscription id are ignored.")


def delete(client_id: str, client_secret: str, sub_id: int) -> None:
    resp = requests.delete(f"{SUBSCRIPTIONS_URL}/{sub_id}", timeout=TIMEOUT_SEC,
                           params={"client_id": client_id, "client_secret": client_secret})
    if resp.status_code != 204 and not resp.ok:
        sys.exit(f"Could not delete subscription {sub_id} (HTTP {resp.status_code}): {resp.text}")
    print(f"Deleted subscription {sub_id}.")


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("command", choices=["show", "create", "delete"])
    parser.add_argument("--id", type=int, help="subscription id (delete)")
    parser.add_argument("--client-id", default=os.environ.get("STRAVA_CLIENT_ID", DEFAULT_CLIENT_ID))
    parser.add_argument("--callback-url", default=DEFAULT_CALLBACK)
    args = parser.parse_args(argv)

    client_secret = _secret("STRAVA_CLIENT_SECRET", "Strava client secret")
    if args.command == "show":
        show(args.client_id, client_secret)
    elif args.command == "create":
        create(args.client_id, client_secret, args.callback_url,
               _secret("STRAVA_VERIFY_TOKEN", "Webhook verify token"))
    else:
        if args.id is None:
            sys.exit("delete needs --id (see `show`)")
        delete(args.client_id, client_secret, args.id)


if __name__ == "__main__":
    main()

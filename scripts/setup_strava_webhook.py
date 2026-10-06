import json
import os

import requests

# Your Strava API credentials
CLIENT_ID = os.environ.get("STRAVA_CLIENT_ID", "157155")  # public OAuth client id
CLIENT_SECRET = os.environ.get("STRAVA_CLIENT_SECRET") or input("Enter your Strava Client Secret: ").strip()

# Your Webhook Callback URL and Verify Token
CALLBACK_URL = "https://europe-west2-athlethium-app.cloudfunctions.net/strava_webhook"
# Never commit this value; supply it at run time.
VERIFY_TOKEN = os.environ.get("STRAVA_VERIFY_TOKEN") or input("Enter the webhook verify token: ").strip()

def view_subscriptions():
    print("Fetching current subscriptions...")
    res = requests.get(
        "https://www.strava.com/api/v3/push_subscriptions",
        params={
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET
        },
        timeout=15
    )
    if res.ok:
        data = res.json()
        print(json.dumps(data, indent=2))
        return data
    else:
        print(f"Error viewing subscriptions: {res.text}")
        return []

def create_subscription():
    print(f"Attempting to create subscription for: {CALLBACK_URL}")
    res = requests.post(
        "https://www.strava.com/api/v3/push_subscriptions",
        data={
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "callback_url": CALLBACK_URL,
            "verify_token": VERIFY_TOKEN
        }
    )
    if res.ok:
        print("Success! Webhook subscription created.")
        print(json.dumps(res.json(), indent=2))
    else:
        print(f"Failed to create subscription. Status Code: {res.status_code}")
        print(res.text)

if __name__ == "__main__":
    if not CLIENT_SECRET or not VERIFY_TOKEN:
        print("Error: Client Secret and verify token are required.")
        exit(1)

    subs = view_subscriptions()

    if len(subs) > 0:
        print("\nIt looks like you already have active subscriptions.")
        print("Strava only allows ONE active webhook subscription per application.")
        choice = input("Do you want to delete the existing subscription and create a new one? (y/n): ")
        if choice.lower() == 'y':
            sub_id = subs[0]['id']
            print(f"Deleting subscription {sub_id}...")
            del_res = requests.delete(
                f"https://www.strava.com/api/v3/push_subscriptions/{sub_id}",
                params={
                    "client_id": CLIENT_ID,
                    "client_secret": CLIENT_SECRET
                }
            )
            if del_res.ok:
                print("Deleted successfully.")
                create_subscription()
            else:
                print(f"Failed to delete: {del_res.text}")
    else:
        print("\nNo existing subscriptions found. Creating one now...")
        create_subscription()

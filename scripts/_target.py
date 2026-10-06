"""
Shared safety guard for admin scripts.

Scripts default to the local emulator (demo-athlethium). Touching a real project requires
naming it explicitly AND passing --i-understand-this-is-production.
"""

import argparse
import os
import sys

DEMO_PROJECT = "demo-athlethium"


def add_target_args(parser: argparse.ArgumentParser):
    parser.add_argument("--project", default=DEMO_PROJECT,
                        help=f"Firebase project id (default: {DEMO_PROJECT}, emulator only)")
    parser.add_argument("--i-understand-this-is-production", dest="confirm_prod", action="store_true",
                        help="Required to run against any non-demo project")


def init_firebase(args):
    import firebase_admin
    from firebase_admin import firestore

    if args.project.startswith("demo-"):
        os.environ.setdefault("FIRESTORE_EMULATOR_HOST", "127.0.0.1:8080")
    else:
        if not args.confirm_prod:
            sys.exit(f"Refusing to touch real project '{args.project}' without --i-understand-this-is-production")
        if os.environ.get("FIRESTORE_EMULATOR_HOST"):
            sys.exit("FIRESTORE_EMULATOR_HOST is set but a real project was requested; unset one of them.")
    os.environ["GCLOUD_PROJECT"] = args.project
    if not firebase_admin._apps:
        firebase_admin.initialize_app(options={"projectId": args.project})
    print(f"Target project: {args.project}"
          + (f" (emulator {os.environ['FIRESTORE_EMULATOR_HOST']})" if os.environ.get("FIRESTORE_EMULATOR_HOST") else ""))
    return firestore.client()

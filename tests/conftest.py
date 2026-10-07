"""
Shared pytest configuration.

Production safety: every test run is pinned to a `demo-*` Firebase project. Demo projects can
only ever talk to the Emulator Suite, and real credentials are stripped from the environment,
so nothing here can reach the production `athlethium-app` project.
"""

import os

import pytest
import requests

PROJECT_ID = "demo-athlethium"
BUCKET = f"{PROJECT_ID}.appspot.com"

# --- Production guard (runs at import, before any Firebase code is imported) -----------------
_project = os.environ.setdefault("GCLOUD_PROJECT", PROJECT_ID)
if not _project.startswith("demo-"):
    raise pytest.UsageError(
        f"Refusing to run tests against non-demo Firebase project '{_project}'. "
        "Tests must only ever target the emulators (project id starting with 'demo-')."
    )
os.environ.pop("GOOGLE_APPLICATION_CREDENTIALS", None)
os.environ["FIREBASE_CONFIG"] = f'{{"projectId":"{_project}","storageBucket":"{BUCKET}"}}'

EMULATOR_ENV = ("FIRESTORE_EMULATOR_HOST", "FIREBASE_AUTH_EMULATOR_HOST", "FIREBASE_STORAGE_EMULATOR_HOST")
EMULATORS_UP = all(os.environ.get(k) for k in EMULATOR_ENV)
REQUIRE_EMULATORS = os.environ.get("REQUIRE_EMULATORS") == "1"

if EMULATORS_UP:
    # The Admin SDK uses STORAGE_EMULATOR_HOST (with scheme) for google-cloud-storage.
    os.environ.setdefault("STORAGE_EMULATOR_HOST", "http://" + os.environ["FIREBASE_STORAGE_EMULATOR_HOST"])

import firebase_admin  # noqa: E402
from firebase_admin import credentials  # noqa: E402
from google.auth.credentials import AnonymousCredentials  # noqa: E402


class _EmulatorCredential(credentials.Base):
    """No real credentials exist in tests; the emulators accept anonymous access."""

    def get_credential(self):
        return AnonymousCredentials()


if not firebase_admin._apps:
    firebase_admin.initialize_app(_EmulatorCredential(), options={"projectId": PROJECT_ID, "storageBucket": BUCKET})


def pytest_collection_modifyitems(config, items):
    if EMULATORS_UP:
        return
    if REQUIRE_EMULATORS:
        raise pytest.UsageError(
            "REQUIRE_EMULATORS=1 but emulator env vars are missing. Run ./scripts/test.sh."
        )
    skip = pytest.mark.skip(reason="Firebase emulators not running (use ./scripts/test.sh)")
    for item in items:
        if "emulator" in item.keywords or "functions_emulator" in item.keywords:
            item.add_marker(skip)


# --- Emulator helpers --------------------------------------------------------------------------

def _firestore_url() -> str:
    return f"http://{os.environ['FIRESTORE_EMULATOR_HOST']}"


def _auth_url() -> str:
    return f"http://{os.environ['FIREBASE_AUTH_EMULATOR_HOST']}"


def clear_emulators():
    requests.delete(
        f"{_firestore_url()}/emulator/v1/projects/{PROJECT_ID}/databases/(default)/documents", timeout=10
    ).raise_for_status()
    requests.delete(f"{_auth_url()}/emulator/v1/projects/{PROJECT_ID}/accounts", timeout=10).raise_for_status()


@pytest.fixture
def emulators():
    """Clean Firestore + Auth emulator state for one test."""
    clear_emulators()
    yield
    clear_emulators()


@pytest.fixture
def db(emulators):
    from firebase_admin import firestore

    return firestore.client()


@pytest.fixture
def seed(db):
    """seed({"users/u1": {...}, "workouts/w1": {...}}) writes documents to the Firestore emulator."""

    def _seed(docs):
        for path, data in docs.items():
            db.document(path).set(data)

    return _seed


class AuthUser:
    def __init__(self, uid: str, email: str, id_token: str):
        self.uid = uid
        self.email = email
        self.id_token = id_token

    @property
    def headers(self):
        return {"Authorization": f"Bearer {self.id_token}"}


@pytest.fixture
def make_user(emulators):
    """Create a real Auth-emulator account and return its uid + ID token."""
    counter = {"n": 0}

    def _make(email: str = None, password: str = "password123") -> AuthUser:
        counter["n"] += 1
        email = email or f"athlete{counter['n']}@example.test"
        resp = requests.post(
            f"{_auth_url()}/identitytoolkit.googleapis.com/v1/accounts:signUp?key=fake-api-key",
            json={"email": email, "password": password, "returnSecureToken": True},
            timeout=10,
        )
        resp.raise_for_status()
        body = resp.json()
        return AuthUser(body["localId"], email, body["idToken"])

    return _make

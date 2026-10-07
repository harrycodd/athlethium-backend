"""Strava OAuth: state handling, token storage and every failure mode of the Strava API (mocked)."""

import time
import urllib.parse

import pytest
import requests
import requests_mock as rm

from services.strava_service import STRAVA_DEAUTHORIZE_URL, STRAVA_TOKEN_URL, StravaService

pytestmark = pytest.mark.emulator

TOKENS = {"access_token": "acc-1", "refresh_token": "ref-1", "expires_at": 1999999999, "athlete": {"id": 42}}


@pytest.fixture(autouse=True)
def strava_env(monkeypatch):
    monkeypatch.setenv("STRAVA_CLIENT_SECRET", "test-secret")


@pytest.fixture
def strava():
    with rm.Mocker(real_http=True) as m:
        yield m


def start(main_module, call, user, return_url="athlethium://settings"):
    body = {} if return_url is None else {"returnUrl": return_url}
    return call(main_module.strava_auth_start, json=body, user=user)


def callback(main_module, call, **query):
    return call(main_module.strava_callback, method="GET", query=query)


class TestStart:
    def test_issues_state_bound_to_user(self, main_module, call, make_user, db):
        user = make_user()
        r = start(main_module, call, user)
        assert r.status == 200
        state = r.json["state"]
        qs = urllib.parse.parse_qs(urllib.parse.urlsplit(r.json["authUrl"]).query)
        assert qs["state"] == [state] and qs["client_id"] == ["157155"]
        saved = db.document(f"oauthStates/{state}").get().to_dict()
        assert saved["uid"] == user.uid and saved["returnUrl"] == "athlethium://settings"

    def test_default_return_url(self, main_module, call, make_user):
        assert start(main_module, call, make_user(), return_url=None).json["returnUrl"] == "athlethium://settings"

    @pytest.mark.parametrize("url", ["https://evil.example/phish", "javascript:alert(1)", "", 5, "athlethium://" + "x" * 600])
    def test_rejects_untrusted_return_urls(self, main_module, call, make_user, url):
        assert start(main_module, call, make_user(), return_url=url).status == 400

    def test_expo_dev_return_url_allowed(self, main_module, call, make_user):
        assert start(main_module, call, make_user(), return_url="exp://192.168.1.2:8081/--/settings").status == 200


class TestCallback:
    def test_success_stores_tokens_server_side_only(self, main_module, call, make_user, db, strava):
        user = make_user()
        db.document(f"users/{user.uid}").set({"stravaAccessToken": "legacy", "displayName": "A"})
        state = start(main_module, call, user, "athlethium://settings?tab=apps").json["state"]
        strava.post(STRAVA_TOKEN_URL, json=TOKENS)

        r = callback(main_module, call, state=state, code="abc")
        assert r.status == 302
        assert r.headers["Location"] == "athlethium://settings?tab=apps&success=true"
        sent = urllib.parse.parse_qs(strava.request_history[-1].text)
        assert sent["client_secret"] == ["test-secret"] and sent["code"] == ["abc"]

        user_doc = db.document(f"users/{user.uid}").get().to_dict()
        assert user_doc == {"displayName": "A", "stravaConnected": True, "stravaAthleteId": "42"}
        private = db.document(f"users/{user.uid}/private/strava").get().to_dict()
        assert private["accessToken"] == "acc-1" and private["refreshToken"] == "ref-1"

    def test_state_is_single_use(self, main_module, call, make_user, strava):
        state = start(main_module, call, make_user()).json["state"]
        strava.post(STRAVA_TOKEN_URL, json=TOKENS)
        assert callback(main_module, call, state=state, code="abc").status == 302
        assert callback(main_module, call, state=state, code="abc").status == 400

    @pytest.mark.parametrize("state", [None, "forged", "a/b", "x" * 200])
    def test_unknown_state_rejected_without_redirect(self, main_module, call, state):
        query = {"code": "abc"} if state is None else {"code": "abc", "state": state}
        r = callback(main_module, call, **query)
        assert r.status == 400 and "Location" not in r.headers

    def test_legacy_client_built_state_rejected(self, main_module, call):
        forged = '{"uid": "victim", "return_url": "https://evil.example"}'
        r = callback(main_module, call, state=forged, code="attacker-code")
        assert r.status == 400 and "Location" not in r.headers

    def test_expired_state(self, main_module, call, make_user, db):
        user = make_user()
        db.document("oauthStates/old").set({"uid": user.uid, "provider": "strava", "returnUrl": "athlethium://x",
                                            "expiresAt": int(time.time()) - 1})
        assert callback(main_module, call, state="old", code="abc").status == 400

    def test_wrong_provider_state(self, main_module, call, db):
        db.document("oauthStates/s").set({"uid": "u", "provider": "wahoo", "expiresAt": int(time.time()) + 60})
        assert callback(main_module, call, state="s", code="abc").status == 400

    def test_tampered_stored_return_url_falls_back(self, main_module, call, db, strava):
        db.document("oauthStates/s").set({"uid": "u", "provider": "strava", "returnUrl": "https://evil.example",
                                          "expiresAt": int(time.time()) + 60})
        strava.post(STRAVA_TOKEN_URL, json=TOKENS)
        assert callback(main_module, call, state="s", code="c").headers["Location"].startswith("athlethium://settings")

    def test_user_denied_access(self, main_module, call, make_user):
        state = start(main_module, call, make_user()).json["state"]
        r = callback(main_module, call, state=state, error="access_denied")
        assert r.headers["Location"] == "athlethium://settings?error=access_denied"

    def test_missing_code(self, main_module, call, make_user):
        state = start(main_module, call, make_user()).json["state"]
        assert callback(main_module, call, state=state).headers["Location"].endswith("error=missing_code")

    @pytest.mark.parametrize("mock_kwargs,code", [
        ({"exc": requests.exceptions.ConnectTimeout}, "strava_timeout"),
        ({"exc": requests.exceptions.ReadTimeout}, "strava_timeout"),
        ({"exc": requests.exceptions.ConnectionError}, "strava_unreachable"),
        ({"status_code": 429, "json": {"message": "Rate Limit Exceeded"}}, "strava_rate_limited"),
        ({"status_code": 401, "json": {"message": "Authorization Error"}}, "strava_auth_rejected"),
        ({"status_code": 400, "json": {"message": "Bad Request", "errors": [{"code": "invalid"}]}},
         "strava_auth_rejected"),
        ({"status_code": 503, "text": "unavailable"}, "strava_unavailable"),
        ({"status_code": 200, "text": "<html>oops</html>"}, "strava_bad_response"),
        ({"status_code": 200, "json": ["unexpected"]}, "strava_bad_response"),
        ({"status_code": 200, "json": {"access_token": "only-access"}}, "strava_bad_response"),
    ])
    def test_strava_failure_modes(self, main_module, call, make_user, db, strava, mock_kwargs, code):
        user = make_user()
        state = start(main_module, call, user).json["state"]
        strava.post(STRAVA_TOKEN_URL, **mock_kwargs)
        r = callback(main_module, call, state=state, code="abc")
        assert r.status == 302 and r.headers["Location"] == f"athlethium://settings?error={code}"
        assert not db.document(f"users/{user.uid}/private/strava").get().exists

    def test_missing_secret_configuration(self, main_module, call, monkeypatch):
        monkeypatch.delenv("STRAVA_CLIENT_SECRET")
        assert callback(main_module, call, state="s", code="c").status == 500


class TestDisconnect:
    def connect(self, db, user):
        db.document(f"users/{user.uid}").set({"stravaConnected": True, "stravaAthleteId": "42",
                                              "stravaRefreshToken": "legacy"})
        db.document(f"users/{user.uid}/private/strava").set({"accessToken": "acc-1", "refreshToken": "ref-1"})

    def test_revokes_and_deletes_tokens(self, main_module, call, make_user, db, strava):
        user = make_user()
        self.connect(db, user)
        strava.post(STRAVA_DEAUTHORIZE_URL, json={"access_token": "acc-1"})
        r = call(main_module.strava_disconnect, json={}, user=user)
        assert r.status == 200 and r.json["data"]["revoked"] is True
        assert db.document(f"users/{user.uid}").get().to_dict() == {"stravaConnected": False}
        assert not db.document(f"users/{user.uid}/private/strava").get().exists

    @pytest.mark.parametrize("mock_kwargs", [{"exc": requests.exceptions.ReadTimeout}, {"status_code": 401}])
    def test_local_cleanup_even_if_strava_fails(self, main_module, call, make_user, db, strava, mock_kwargs):
        user = make_user()
        self.connect(db, user)
        strava.post(STRAVA_DEAUTHORIZE_URL, **mock_kwargs)
        r = call(main_module.strava_disconnect, json={}, user=user)
        assert r.status == 200 and r.json["data"]["revoked"] is False
        assert not db.document(f"users/{user.uid}/private/strava").get().exists

    def test_not_connected_is_noop(self, main_module, call, make_user, db):
        user = make_user()
        assert call(main_module.strava_disconnect, json={}, user=user).status == 200
        assert db.document(f"users/{user.uid}").get().to_dict() == {"stravaConnected": False}

    def test_private_doc_without_access_token(self, main_module, call, make_user, db):
        user = make_user()
        db.document(f"users/{user.uid}/private/strava").set({"refreshToken": "r"})
        assert call(main_module.strava_disconnect, json={}, user=user).json["data"]["revoked"] is False


def test_with_query_and_allow_list_helpers():
    from services.strava_service import is_allowed_return_url, with_query
    assert with_query("athlethium://a", x="1") == "athlethium://a?x=1"
    assert with_query("athlethium://a?b=2", x="1 2") == "athlethium://a?b=2&x=1+2"
    assert is_allowed_return_url("EXPS://host/path")
    assert not is_allowed_return_url(None)


def test_service_start_rejects_bad_url_directly(emulators):
    with pytest.raises(ValueError):
        StravaService.start_authorization("u", "http://x", "1", "https://cb")

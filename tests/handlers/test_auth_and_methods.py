"""Every app-facing endpoint rejects unauthenticated calls and wrong HTTP methods."""

import pytest

pytestmark = pytest.mark.emulator

APP_ENDPOINTS = ["update_user_profile", "generate_training_session", "complete_manual_workout",
                 "upload_workout_fit", "strava_auth_start", "strava_disconnect"]


@pytest.mark.parametrize("endpoint", APP_ENDPOINTS)
@pytest.mark.parametrize("headers", [
    {},
    {"Authorization": "Bearer"},
    {"Authorization": "Bearer not-a-jwt"},
    {"Authorization": "Basic dXNlcjpwYXNz"},
])
def test_unauthenticated_is_401(main_module, call, endpoint, headers):
    r = call(getattr(main_module, endpoint), json={"userId": "victim"}, headers=headers)
    assert r.status == 401
    assert r.json == {"error": "Authentication required"}


@pytest.mark.parametrize("endpoint", APP_ENDPOINTS)
def test_get_is_405(main_module, call, make_user, endpoint):
    assert call(getattr(main_module, endpoint), method="GET", user=make_user()).status == 405


@pytest.mark.parametrize("endpoint", ["update_user_profile", "generate_training_session"])
def test_cannot_act_as_another_user(main_module, call, make_user, endpoint):
    r = call(getattr(main_module, endpoint), json={"userId": "someone-else"}, user=make_user())
    assert r.status == 403


@pytest.mark.parametrize("endpoint", ["update_user_profile", "generate_training_session", "complete_manual_workout",
                                      "strava_auth_start"])
def test_non_object_json_is_400(main_module, call, make_user, endpoint):
    r = call(getattr(main_module, endpoint), json=["not", "an", "object"], user=make_user())
    assert r.status == 400


def test_unexpected_errors_do_not_leak_details(main_module, call, make_user, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("secret internal detail")

    monkeypatch.setattr(main_module.UserService, "get_user_profile", boom)
    r = call(main_module.generate_training_session, json={}, user=make_user())
    assert r.status == 500 and "secret" not in r.text

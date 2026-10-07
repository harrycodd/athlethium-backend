import pytest

from tests.factories import make_profile_doc

pytestmark = pytest.mark.emulator


def test_saves_normalised_profile_for_token_user(main_module, call, make_user, db):
    user = make_user()
    r = call(main_module.update_user_profile, json={"profile": make_profile_doc(timezone="Europe/London")}, user=user)
    assert r.status == 200, r.text
    assert r.json["userId"] == user.uid and r.json["wizardCompleted"] is True
    saved = db.document(f"users/{user.uid}").get().to_dict()
    assert saved["focused_sports"] == ["cycling"] and saved["timezone"] == "Europe/London"


def test_body_without_profile_wrapper_and_matching_userid(main_module, call, make_user, db):
    user = make_user()
    r = call(main_module.update_user_profile, json={"userId": user.uid, **make_profile_doc()}, user=user)
    assert r.status == 200
    assert db.document(f"users/{user.uid}").get().exists


def test_validation_errors_are_400_with_details(main_module, call, make_user, db):
    user = make_user()
    r = call(main_module.update_user_profile, json={"profile": make_profile_doc(weekly_hours=99)}, user=user)
    assert r.status == 400 and r.json["error"] == "Validation failed"
    assert any("weekly_hours" in d for d in r.json["details"])
    assert not db.document(f"users/{user.uid}").get().exists


def test_partial_update_merges(main_module, call, make_user, seed, db):
    user = make_user()
    seed({f"users/{user.uid}": make_profile_doc()})
    r = call(main_module.update_user_profile, json={"profile": {"units": "Imperial"}, "isPartial": True}, user=user)
    assert r.status == 200
    saved = db.document(f"users/{user.uid}").get().to_dict()
    assert saved["units"] == "Imperial" and saved["displayName"] == "Test Athlete"


def test_is_partial_must_be_boolean(main_module, call, make_user):
    r = call(main_module.update_user_profile, json={"profile": {}, "isPartial": "yes"}, user=make_user())
    assert r.status == 400


def test_empty_body_validates_as_full_profile(main_module, call, make_user):
    r = call(main_module.update_user_profile, user=make_user())
    assert r.status == 400 and "displayName is required and cannot be empty" in r.json["details"]


def test_cannot_set_server_fields_via_profile(main_module, call, make_user, db):
    user = make_user()
    doc = make_profile_doc()
    doc.update(stravaConnected=True, stravaAccessToken="x")
    assert call(main_module.update_user_profile, json={"profile": doc}, user=user).status == 200
    saved = db.document(f"users/{user.uid}").get().to_dict()
    assert "stravaConnected" not in saved and "stravaAccessToken" not in saved

"""scripts/strava_webhook_subscription.py against a mocked Strava API (never the real one)."""

import urllib.parse

import pytest
import requests_mock as rm

from scripts import strava_webhook_subscription as script

URL = script.SUBSCRIPTIONS_URL


@pytest.fixture(autouse=True)
def secrets(monkeypatch):
    monkeypatch.setenv("STRAVA_CLIENT_SECRET", "s3cret")
    monkeypatch.setenv("STRAVA_VERIFY_TOKEN", "verify-me")


@pytest.fixture
def strava():
    with rm.Mocker() as m:
        yield m


def test_create_points_strava_at_the_deployed_webhook(strava, capsys):
    strava.post(URL, json={"id": 77})
    script.main(["create"])
    sent = urllib.parse.parse_qs(strava.request_history[0].text)
    assert sent["callback_url"] == ["https://europe-west2-athlethium-app.cloudfunctions.net/strava_webhook"]
    assert sent["verify_token"] == ["verify-me"] and sent["client_secret"] == ["s3cret"]
    assert "Subscription id: 77" in capsys.readouterr().out


def test_show_and_delete(strava, capsys):
    strava.get(URL, json=[{"id": 77, "callback_url": "x"}])
    script.main(["show"])
    assert '"id": 77' in capsys.readouterr().out
    strava.delete(f"{URL}/77", status_code=204)
    script.main(["delete", "--id", "77"])
    assert "Deleted subscription 77" in capsys.readouterr().out


def test_show_when_none(strava, capsys):
    strava.get(URL, json=[])
    script.main(["show"])
    assert "No subscription" in capsys.readouterr().out


@pytest.mark.parametrize("argv,method,path", [(["create"], "post", ""), (["show"], "get", ""),
                                              (["delete", "--id", "5"], "delete", "/5")])
def test_strava_errors_exit_with_the_reason(strava, argv, method, path):
    getattr(strava, method)(URL + path, status_code=403, text="verify token mismatch")
    with pytest.raises(SystemExit, match="403"):
        script.main(argv)


def test_delete_needs_an_id():
    with pytest.raises(SystemExit, match="--id"):
        script.main(["delete"])


def test_missing_secret_is_prompted_and_required(monkeypatch):
    monkeypatch.delenv("STRAVA_CLIENT_SECRET")
    monkeypatch.setattr(script.getpass, "getpass", lambda prompt: "")
    with pytest.raises(SystemExit, match="STRAVA_CLIENT_SECRET"):
        script.main(["show"])

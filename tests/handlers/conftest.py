"""In-process handler tests: real handler code + Firestore/Auth/Storage emulators."""

import json as jsonlib

import pytest
from flask import Flask, request

pytestmark = pytest.mark.emulator


_APP = Flask("handler-tests")


class Result:
    def __init__(self, resp):
        self.status = resp.status_code
        self.headers = resp.headers
        self.text = resp.get_data(as_text=True)

    @property
    def json(self):
        return jsonlib.loads(self.text)


@pytest.fixture
def call():
    """call(handler, method="POST", json=..., user=AuthUser|None, data=..., query=..., headers=...)"""

    def _call(handler, method="POST", json=None, user=None, data=None, query=None, headers=None):
        hdrs = dict(headers or {})
        if user is not None:
            hdrs.update(user.headers)
        with _APP.test_request_context(method=method, json=json, data=data, query_string=query, headers=hdrs):
            return Result(_APP.make_response(handler(request)))

    return _call


@pytest.fixture
def main_module(emulators):
    import main

    return main

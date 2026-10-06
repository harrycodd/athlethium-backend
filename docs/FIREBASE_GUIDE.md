# Developer Guide: Cloud Functions

For setup, running the emulators and running the tests, see the [project README](../README.md).
Always develop against the `demo-athlethium` emulator project, never `athlethium-app`.

## Adding an HTTP endpoint

Follow the pattern used in `functions/main.py`:

```python
@https_fn.on_request(region=REGION, invoker="public", cors=CORS)
def my_endpoint(req: https_fn.Request) -> https_fn.Response:
    """One line on what it does for the signed-in athlete."""

    def handle():
        if (resp := _require_post(req)) is not None:
            return resp
        uid = require_uid(req)          # 401 unless a valid Firebase ID token is sent
        body = _json_body(req)
        _check_claimed_user(body, uid)  # a body userId must match the token
        ...                             # raise BadRequest / WorkoutNotFound / PermissionError
        return _json({"message": "ok"})

    return _run("my_endpoint", handle)  # maps exceptions to 400/401/403/404/500
```

Rules:
- **User identity:** take the user only from `require_uid`. Never trust a `userId` from the
  request.
- **Secrets:** declare them with `secrets=["NAME"]` and read them from `os.environ`.
  - Production: set them with `npx firebase functions:secrets:set NAME --project athlethium-app`.
  - Emulators: add a dummy value to `functions/.secret.local` (git-ignored).
- **Tests:**
  - Add handler tests in `tests/handlers/`. They run in-process against the Firestore emulator.
  - If the endpoint is part of a user flow, add an HTTP case to `tests/integration/`.
- **Dependencies:** add new runtime dependencies to `functions/requirements.txt`, pinned.

## Logs

- Emulator logs appear in the terminal and in the Emulator UI (http://127.0.0.1:4000).
- Production logs: `npx firebase functions:log --project athlethium-app`.

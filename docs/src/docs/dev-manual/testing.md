# Testing

Comaney uses end-to-end Selenium tests. All tests exercise the running application through a real browser against a live Docker stack. There are no unit or integration tests at the model or view layer.

## Prerequisites

```bash
# macOS (required for mysqlclient to build)
brew install pkg-config mysql-client

pip install -r requirements-test.txt
```

## Running the tests

The stack must be running before you start the tests.

```bash
# Terminal 1: start the stack
docker compose up

# Terminal 2: run the tests
cd tests && pytest -xsx
```

The tests expect:

- The Comaney app at `http://localhost:8080`
- Mailpit (email capture) at `http://localhost:8030`
- A Docker container named `comaney-web-1`

If your container name differs, adjust `DOCKER_WEB` in `tests/conftest.py`.

## Test conventions

These rules are mandatory:

**UI-first verification.** A test that checks whether a feature works must verify the result through the UI, not the API.

- Correct: create a tag via the UI, verify it appears in the UI list.
- Wrong: create a tag via the UI, verify via `GET /api/v1/tags/`.

**API setup is allowed.** The API may be used for setup and teardown only. For example, to test deletion, it is fine to create the object via the API (faster), then delete it via the UI, and verify it is gone via the UI.

**No direct database access** from tests.

## Test ordering

Test files are numbered with a two-digit prefix (`test_01_`, `test_02_`, ...) and run in that order. Some later files depend on state created by earlier ones (for example, a user account created in `test_01_` is reused throughout). Run the full suite, not individual files, unless you know the dependencies.

## Triggering server-side operations

Some tests need to trigger cron-driven behaviour (notifications, auto-settlement, carry-overs). Use the `run_cmd` helper from `conftest.py`:

```python
run_cmd("run_cron")
```

This runs `python manage.py <command>` inside the running container via `docker exec`.

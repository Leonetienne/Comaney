# Testing

Comaney uses end-to-end Selenium tests. Every test exercises the running application through a real browser against a live Docker stack. There are no unit or integration tests at the model or view layer: if the UI works, the feature works.

## Prerequisites

Python and the test dependencies must be installed locally. The app itself runs in Docker.

```bash
# macOS: required for mysqlclient to build
brew install pkg-config mysql-client

pip install -r requirements-test.txt
```

## Running the tests

The Docker stack must be running before you start:

```bash
# Terminal 1
docker compose up

# Terminal 2: run the full suite
cd tests_new && pytest -vsx

# Run a single file
cd tests_new && pytest -vsx test_expenses.py

# Run a single test
cd tests_new && pytest -vsx test_expenses.py::TestExpenseCreate::test_create_expense
```

Always use `-vsx`: verbose output, stop on first failure, no output capture. This makes failures immediately readable.

The suite expects:

- The Comaney app at `http://localhost:8080`
- Mailpit (email capture) at `http://localhost:8030`
- A Docker container named `comaney-web-1`

If your container name differs, adjust `DOCKER_WEB` in `tests_new/helpers.py`.

## Test mentality

**Each file is fully self-contained.** Every test file creates its own user via `setup_user()` and cleans it up in a module-scoped fixture. Files do not share state and can be run in any order or in isolation.

**The API exists for setup and teardown.** Creating or deleting objects through the API before or after a UI interaction is fine and encouraged: it keeps tests focused on the thing being tested rather than on repetitive setup steps.

**Verification layer depends on what is being tested.** Ask: what is this test asserting?

- If the assertion is about UI presentation ("does the tag appear in the list", "is the deactivated badge shown"), verify through the UI.
- If the assertion is about whether the UI can perform an action ("does submitting the form create a tag"), and the API response is independently covered by its own tests, verifying through the API is acceptable.

Never use the API to verify something whose correctness only exists in the UI. If it needs to show up on screen, check the screen.

## Triggering server-side operations

```python
from helpers import run_cmd

run_cmd("run_cron")
run_cmd("generate_scheduled_expenses", "--year", "2026")
```

## Shared helpers

All helpers live in `tests_new/helpers.py`:

- `setup_user(driver, w)` / `cleanup_user(email)`: full user lifecycle (register, confirm email, log in, generate API key).
- `api_get` / `api_post` / `api_patch` / `api_delete`: Bearer-authenticated API calls.
- `fill`, `click`, `submit`, `wait_url`, `wait_text`: browser interaction shortcuts.
- `server_today()`: reads the current date from inside the container (avoids timezone drift).
- `run_cmd(*args)`: runs a Django management command in the container.

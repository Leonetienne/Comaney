# Security Audit: Comaney

Date: 2026-06-16
Scope: pre-release review of the whole application (auth, API, dashboard cards, buddies/projects, settings).

This is written for a single, self-hosted, low-traffic instance, so I have deliberately skipped
theoretical or low-yield nitpicks and ranked by "would I actually fix this before calling it
releasable". Each item has: what it is, how an e2e test could trigger it, and how to fix it.

Two things worth fixing properly (1 and 2), two worth fixing soon (3-4), and a short list of
minor notes at the end.

Note: transport security (HTTPS, HSTS, SSL redirect, secure-cookie flags) is intentionally left out
— this is self-hosted and may run over plain HTTP on a private network or behind a TLS-terminating
reverse proxy, so that is the admin's deployment decision, not the app's to force.

---

## 1. Stored, cross-user XSS via JSON embedded in `<script>` with `|safe`  — CRITICAL

### Description
Several views serialise data with `json.dumps(...)` (or `mark_safe(json.dumps(...))`) and the
template prints it inside a `<script>` block through the `|safe` filter. `json.dumps` does **not**
escape `<`, `>` or `/`, so any user-controlled string that contains `</script>` breaks out of the
script element and the rest is parsed as HTML.

The dangerous part is that some of these strings are controlled by **other users**:

- Project member names → [`all_members_json` in projects.py:334](buddies/views/projects.py:334),
  rendered at [`project_detail.html:563`](buddies/templates/buddies/project_detail.html:563)
  (`var MEMBERS = {{ all_members_json|safe }};`), plus `RAW`, `SIMPLIFIED`, `PAIRS`.
- Buddy names / debts → [`main.py:264-277`](buddies/views/main.py:264) rendered at
  [`buddy_summary.html:114`](buddies/templates/buddies/buddy_summary.html:114) (`DEBTS`, `MEMBERS`, `ME_AVATAR`).
- A partner's tag/category titles → [`partnership.py:164`](buddies/views/partnership.py:164) rendered at
  [`partnership_onboarding.html:156`](buddies/templates/buddies/partnership_onboarding.html:156).
- Project/buddy names → `projects_data_json` / `single_buddies_json` in
  [`budget/views/expenses.py:60`](budget/views/expenses.py:60), used by
  [`express_creation.html:16`](budget/templates/budget/express_creation.html:16) and `_expense_assignment.html`.

Names and tag/category titles have no HTML sanitisation; the profile form only enforces
`max_length` ([`feusers/forms.py:6`](feusers/forms.py:6)). Because Django's session cookie is
HttpOnly by default the attacker can't read `document.cookie`, but the injected script runs in the
victim's authenticated session and can read the CSRF token from the page and call any endpoint as
the victim (change settings, create/delete expenses, etc.) — effectively account takeover of every
co-member who opens the affected page.

A related, lower-risk instance is `{{ message|safe }}` at
[`buddy_summary.html:21`](buddies/templates/buddies/buddy_summary.html:21); flash messages currently
only interpolate counts and `EmailField`-validated addresses, so it isn't directly exploitable today,
but it's the same footgun.

### How an e2e test could trigger it
1. User A and User B share a project (existing project fixtures in `ctx`).
2. As User A, set first name to `</script><script>window.__xss=1</script>` via the profile form
   (`execute_script` to set the input, submit, per the Selenium notes).
3. Log in as User B, open the shared project detail page, `time.sleep(...)`, then assert
   `driver.execute_script("return window.__xss")` is truthy — i.e. A's payload executed in B's page.
   A safe variant: set the name to `</script><h1 id="pwn">x</h1>` and assert an element `#pwn` exists
   outside the script tag.

### How to fix
Stop hand-rolling JSON into `<script>`. Use Django's built-in `json_script`, which HTML-escapes
`<`, `>`, `&` and emits a typed `<script id="...">` element:

```django
{{ all_members|json_script:"members-data" }}
<script>const MEMBERS = JSON.parse(document.getElementById('members-data').textContent);</script>
```

If you'd rather keep the current shape with minimal churn, route every `json.dumps` that lands in a
template through one helper that escapes the breakout characters, e.g.:

```python
def safe_json(obj):
    return json.dumps(obj).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
```

and keep using `|safe`. Also drop `|safe` from `{{ message|safe }}` (let it auto-escape).
Add a regression test that a name containing `</script>` is rendered escaped.

---

## 2. App boots with a known fallback `SECRET_KEY` — IMPORTANT

### Description
[`settings.py:6`](comaney/settings.py:6) falls back to a hard-coded
`"dev-secret-key-change-in-production"` when `DJANGO_SECRET_KEY` is unset. The key is in a public
repo. Sessions are DB-backed so this doesn't directly let an attacker forge a login cookie, but the
secret still signs CSRF tokens and anything that goes through `django.core.signing`. Running
production on a publicly known key is a latent foot-gun: a single missing env var silently downgrades
those protections with no warning.

### How an e2e test could trigger it
This is a misconfiguration check rather than a UI flow. A test can assert it via a management/shell
command run with `run_cmd`: start the stack **without** `DJANGO_SECRET_KEY` and assert the process
refuses to start (non-zero exit / error log) instead of coming up. Conversely, with the env var set,
it starts normally.

### How to fix
Fail fast in production. Keep a dev default only when `DEBUG`:

```python
SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "")
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = "dev-secret-key-change-in-production"
    else:
        raise ImproperlyConfigured("DJANGO_SECRET_KEY must be set in production.")
```

(You already have the `SYSTEM_MISCONFIGURED` banner pattern — surfacing it there is an acceptable
alternative to a hard crash.)

---

## 3. CSRF on the API's write methods (session auth + `@csrf_exempt`) — IMPORTANT

### Description
Every `/api/v1/*` view is decorated `@csrf_exempt` (e.g.
[`api/views/expenses.py:15`](api/views/expenses.py:15),
[`api/views/account.py:7`](api/views/account.py:7)), and
[`get_api_user`](api/auth.py:4) authenticates with a Bearer token **or**, failing that, the
`feuser_id` session cookie.

The session fallback is genuinely used by the frontend: the expenses list calls
`apiUrl: "/api/v1/expenses/"` ([`expenses_list.html:9`](budget/templates/budget/expenses_list.html:9))
as a **GET** ([`expenses.js:147`](build/js/expenses.js:147)). That read path is fine — CSRF doesn't
apply to safe methods, and a cross-origin site can't read the JSON response without CORS headers.
(All mutations in the UI go through the separate, CSRF-protected `/budget/...` form-POST endpoints,
not the API — see the `csrfmiddlewaretoken` form built at [`expenses.js:268`](build/js/expenses.js:268).)

The problem is the API's **write** methods. `POST /api/v1/expenses/`, `/categories/`, `/tags/`,
`/scheduled/`, plus the `PATCH`/`DELETE` detail endpoints and `PATCH /api/v1/account/`, are all
`@csrf_exempt` yet accept the session cookie. So a logged-in user lured to a malicious page can have
cross-site state-changing requests run against the API on their ambient session, with no CSRF token.
`PATCH`/`DELETE` and `application/json` bodies are incidentally protected by the CORS preflight, but
the create endpoints are reachable with a plain cross-site form using `enctype="text/plain"` to
smuggle a valid JSON body — enough to forge expenses/categories/tags in a victim's account.

### How an e2e test could trigger it
Log in (session cookie set). Without sending any CSRF token, `POST /api/v1/expenses/` with a JSON
body and assert it returns `201` and the expense appears — a write authenticated purely by the
ambient cookie. After the fix, the same session-only POST should be rejected (403), while the
session GET (expenses list) and a Bearer-token POST both still work.

### How to fix
Don't drop the session fallback (the expenses list GET needs it). Instead, enforce CSRF for
**cookie-authenticated** requests and exempt only Bearer-token clients — the standard DRF pattern.
Replace the blanket `@csrf_exempt`/`_require_auth` with one decorator:

```python
from functools import wraps
from django.views.decorators.csrf import csrf_exempt
from django.middleware.csrf import CsrfViewMiddleware

def _require_auth(fn):
    @csrf_exempt                      # we decide CSRF ourselves, per auth type
    @wraps(fn)
    def wrapper(request, *args, **kwargs):
        user = get_api_user(request)
        if not user:
            return _err("Unauthorized — provide a valid Bearer token.", 401)
        # Bearer clients: no ambient cookies, so CSRF is unnecessary.
        # Cookie-authenticated requests: enforce CSRF (no-op on safe methods like GET).
        if not request.headers.get("Authorization", "").startswith("Bearer "):
            reason = CsrfViewMiddleware(lambda r: None).process_view(request, fn, args, kwargs)
            if reason is not None:
                return _err("CSRF verification failed.", 403)
        return fn(request, user, *args, **kwargs)
    return wrapper
```

GET stays exempt (CSRF only checks unsafe methods), the expenses list keeps working, Bearer clients
stay token-only, and session-based writes now need a valid CSRF token the attacker can't supply.
The browser would then send the token via the `X-CSRFToken` header if you ever add UI writes against
the API.

---

## Minor notes (fix if convenient; not release blockers)

- **Demo users can upload pictures / backdrops / backdrop CSS.** The picture, backdrop, and
  `backdrop_settings` actions in [`account.py`](feusers/views/account.py:41) have no `is_demo` guard,
  unlike the other profile actions. A demo visitor could leave an offensive image/CSS that persists
  on the shared demo account until the weekly reset — a "sabotage the shared demo" case per the demo
  policy in CLAUDE.md. Add the same `if feuser.is_demo: return redirect(...)` guard.

- **Any logged-in user can fetch any other user's media by id.** [`media_serve`](comaney/media_serve.py:12)
  only checks that *someone* is logged in, not ownership, so `/media/ppics/<pk>.jpg`,
  `/media/backdrops/<pk>.png`, etc. are enumerable across users. Low sensitivity (profile pictures are
  already shown to buddies) and path traversal is correctly blocked — flagging only because backdrops
  aren't otherwise shared. Scope the lookup to the requester where it matters.

- **Custom-cell Python "sandbox" is exec-based.** [`_run_sandboxed`](budget/dashboard_cards.py:667)
  is actually fairly well locked (no `__builtins__`, dunder-attribute access blocked, imports
  blocked), so I'm not calling it an RCE — but `exec`-based sandboxes are inherently fragile, and the
  2-second timeout uses an unkillable daemon thread, so a malicious authenticated user can pin a CPU
  core with a tight loop (and repeat it). Only reachable by users you've given accounts to. If you
  keep it, consider capping concurrent executions; if you don't need arbitrary code, a small
  expression evaluator would remove the whole class of risk. Solution Remove the python method for cards, along the python sandbox completely. Remove it from docs, from tests and from app code.

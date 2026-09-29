# Security & Robustness Audit — Ticket Set

Prepared for the Comaney dev team. Each ticket is a self-contained markdown file
with: description, technical root cause, proposed fix, and regression-test notes.

Scope of this pass: server crashes / denial of service, access-control gaps,
injection (SQL / CSV / XSS), and deployment hardening. The review covered the
`feusers`, `budget`, `buddies`, `api`, and `comaney` apps plus templates.

## Findings, most severe first

| # | Severity | Title | Area |
|---|----------|-------|------|
| [01](TICKET-01-year-param-500-crash.md) | High | `year` query param out of range crashes views (HTTP 500 / DoS) | `budget/views/_period.py`, `api/utils.py` |
| [02](TICKET-02-buddy-expense-authorization.md) | High | Missing authorization on buddy-expense upfront payer & participants (cross-user writes, IDOR) | `budget/views/expenses.py`, `buddies/services/expense.py` |
| [03](TICKET-03-csv-formula-injection.md) | Medium | CSV formula injection in data exports (cross-user reach) | `comaney/csv_export.py`, `feusers/views/account.py`, `buddies/services/export.py` |
| [04](TICKET-04-rate-limit-in-memory.md) | Medium | Brute-force rate limiting is per-process in-memory and IP-only | `feusers/rate_limit.py` |
| [05](TICKET-05-totp-recovery-no-rate-limit.md) | Medium | TOTP recovery-code verification has no rate limiting | `feusers/views/totp.py` |
| [06](TICKET-06-security-settings-hardening.md) | Medium | Missing secure-cookie / host / transport hardening settings | `comaney/settings.py` |

## Things that were checked and found OK (context for reviewers)

- **SQL injection** via the expense query language: the parser (`budget/query_parser.py`)
  builds Django `Q` objects only; no raw SQL is constructed from user input. OK.
- **Stored XSS via embedded JSON**: every `<script>`-embedded blob traced went through
  `comaney/json_utils.safe_json`, which escapes `<`, `>`, `&`. No `</script>` breakout found. OK.
- **Backdrop custom CSS**: `_sanitize_css` strips `<>{}&@\`\\`, blocking `</style>` breakout,
  and the CSS is only ever rendered for its own owner. Low risk; not ticketed.
- **Path traversal in media serving**: `comaney/media_serve.py` resolves and prefix-checks
  against `MEDIA_ROOT`, and gates backdrops by owner PK. OK.
- **Object ownership in REST API and dashboard-card API**: queries are consistently scoped
  by `owning_feuser` / project membership. OK.

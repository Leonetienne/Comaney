# Introduction

## Purpose

This requirements database specifies the behaviour of Comaney, a self-hosted
budgeting web application. It is the reference for developers, testers and
anyone changing the system.

## Product overview

Comaney answers two questions for its users: where their money goes, and how much
they have left to spend in the current financial month. Users record expenses,
income and savings movements, organise them with categories and tags, and look at
the result on configurable dashboards. On top of personal budgeting, Comaney lets
users split costs with contacts and in projects, keep their label catalogs in sync
with partners, and use an AI service for data entry and classification.

Comaney runs as a Django application in Docker behind a TLS-terminating reverse
proxy, backed by MariaDB. It is administered through environment variables, cron
jobs and management commands.

## User classes

| Class | Description |
|---|---|
| Visitor | Not logged in. Sees the landing page, public pages, registration, login, docs. |
| Feuser | A registered, confirmed user of the web app. |
| Demo user | A shared public feuser account (`is_demo`), restricted so it cannot reach real users or degrade the demo. |
| Project admin | The feuser who administers a given project. |
| API client | A script or app authenticating with a feuser's API key. |
| Instance admin | Operates the deployment: environment, cron, management commands, Django admin (superuser). |
| AI provider author | Writes a provider file for an AI service. |

## Operating environment

- Docker image running Gunicorn with WhiteNoise, MariaDB database.
- A persistent volume at `/app/data` for uploaded media.
- Host cron triggering `run_cron` every 5 minutes and `reset_trial_budgets` monthly.
- Optional SMTP server, optional AI service, optional Yubico OTP validation server.
- Modern browsers; WebAuthn requires a secure context.

## Out of scope (by design)

- Bank account or Open Banking integration.
- Importing bank files (OFX, CSV, QIF).
- Multiple currencies or currency conversion; the currency is a display symbol.
- Passwordless login; security keys are a second factor only.
- Enforcing HTTPS inside the application (handled by the reverse proxy).

## Document conventions

See [README.md](README.md) for the item format, EARS templates and tracing.

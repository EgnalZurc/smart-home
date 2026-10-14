# calendar-service

Google Calendar integration for the smart-home platform: syncs the household's
Google Calendar(s) read-only into a local SQLite cache, surfaces the day's
agenda / upcoming events on the dashboard, and sends configurable Telegram
reminders before events.

Design: [`docs/designs/calendar-service-design.md`](../../docs/designs/calendar-service-design.md).

> **Status: scaffold (Task 8.2).** This is the structural skeleton — FastAPI app,
> health endpoint, SQLite schema and the read-API surface. The Google sync loop,
> reminder tick, pure reminder engine and dashboard widgets land in later tasks.

## What it will do (per design)

- **Sync Google Calendar read-only** every 5–15 min (default 10 min), caching
  expanded event instances locally so the dashboard and reminders never block on
  Google and degrade gracefully when Google is unreachable.
- **Multiple calendars** from one Google account, each labelled and optionally
  bound to a person for reminder routing.
- **Configurable Telegram reminders** (30 min / 1 h / 1 day before) with a hard
  dedup guarantee so an event never reminds twice for the same offset.
- Two **dashboard widgets**: upcoming events and today's agenda.

## Storage (two tiers)

- **Tier 1 — in-memory cache** of upcoming events, rebuilt from SQLite after
  each sync (not yet implemented in the scaffold).
- **Tier 2 — SQLite** (`/app/data/calendar.db`): `calendars`, `events`,
  `people`, `attendee_map`, `reminder_rules`, `reminders_sent`. Uses
  `smart_home_common.sqlite_helpers`. The
  `UNIQUE(event_uid, offset_s, event_start)` constraint on `reminders_sent` is
  the dedup guarantee (design §5.2).

## API (port 8014)

Proxied through the backend under `/api/calendar/*` (SUPER-gated); the browser
never talks to `:8014` directly.

| Endpoint | Status | Purpose |
|----------|--------|---------|
| `GET /health` | ✅ scaffold | `{online, service, db_ok, google_auth_ok, last_sync_ok, last_sync_age_s, reminder_tick_age_s}` |
| `GET /api/health/calendar` | ✅ scaffold | health alias (dashboard catalogue / CI) |
| `GET /api/calendar/upcoming?limit=` | ✅ stub | next N events (reads cache; empty until sync lands) |
| `GET /api/calendar/today` | ✅ stub | today's agenda |

The full read + config API (`/range`, `/calendars`, `/people`, `/rules`,
`/sync`, …) is specified in design §7 and lands with the sync/reminder tasks.

## OAuth (design §2)

Read-only scope (`calendar.readonly`), installed-app refresh-token flow. The
client credentials are secrets in `.env`; the refresh token lives in
`token.json` inside the bind-mounted data dir (mode 600, never logged/returned).
First authorization is a one-time admin step (a `setup_oauth.py` CLI, added in a
later task), not something the container does on its own.

## Configuration

See [`settings.example.toml`](settings.example.toml) for every tunable and
`src/config.py` for the env-var names + defaults.

## Bind-mount permissions (known trap)

The host dir `./data/calendar-service` must exist and be owned by UID 1000
**before** `docker compose up`, or the non-root container cannot create its
SQLite DB nor write `token.json` (`db_ok=false`). The CI deploy step does
`mkdir -p` + `chown 1000:1000` the dir before `docker compose up` (lesson
carried from `metrics-service`).

## Local development

```powershell
# Full CI (ruff + format + bandit + hadolint + pytest, 80% coverage) in the dev container
.\dev.ps1 ci calendar-service
```

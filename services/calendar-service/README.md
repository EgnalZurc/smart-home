# Calendar Service

Syncs Google Calendar events and sends Telegram reminders at configurable offsets.

## Features

- **Google Calendar sync**: Incremental sync using sync tokens
- **Multi-calendar support**: Track multiple calendars with person associations
- **Flexible reminders**: Per-person, per-calendar, or global reminder rules
- **Telegram integration**: Sends formatted reminders via the shared Telegram client

## Architecture

```
┌─────────────────┐      ┌─────────────────┐
│  Google Calendar │◄────│   google_sync   │
│       API        │     │    (OAuth2)     │
└─────────────────┘      └────────┬────────┘
                                  │
                         ┌────────▼────────┐
                         │    database     │
                         │   (SQLite)      │
                         └────────┬────────┘
                                  │
                         ┌────────▼────────┐
                         │ reminder_engine │
                         └────────┬────────┘
                                  │
                         ┌────────▼────────┐
                         │    Telegram     │
                         │  (via async-    │
                         │   http-client)  │
                         └─────────────────┘
```

## Configuration

Environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `PORT` | 8010 | Service port |
| `TELEGRAM_BOT_TOKEN` | required | Telegram bot token |
| `TELEGRAM_CHAT_ID` | required | Chat ID for reminders |
| `GOOGLE_CLIENT_ID` | required | OAuth2 client ID |
| `GOOGLE_CLIENT_SECRET` | required | OAuth2 client secret |
| `CALENDAR_SEED` | `[]` | JSON array of initial calendars |
| `SYNC_INTERVAL_S` | 1800 | Sync interval in seconds (30 min) |
| `DEFAULT_OFFSETS_S` | `[86400,7200,1800]` | Reminder offsets (1d, 2h, 30m) |

### Calendar seed format

```json
[
  {
    "id": "user@gmail.com",
    "label": "User Calendar",
    "person_id": "user",
    "enabled": true
  }
]
```

## API Endpoints

### Health
- `GET /health` - Service health with Google auth status

### Configuration
- `GET /api/calendar/config` - Get current configuration
- `POST /api/calendar/config` - Update configuration

### Events
- `GET /api/calendar/today` - Today's events with timezone support
- `POST /api/calendar/sync` - Trigger immediate sync

## Background Tasks

Three background loops run continuously:

1. **Sync loop** (every 30 min): Fetches calendar updates from Google
2. **Reminder loop** (every 60s): Checks for events needing reminders
3. **Prune loop** (daily): Removes events older than 90 days

## OAuth2 Setup

Before first use, run the OAuth setup script:

```bash
docker exec -it calendar-service python /app/setup_oauth.py
```

This will:
1. Generate an authorization URL
2. Wait for you to authorize the app
3. Store the refresh token in the database

## Dashboard Integration

The dashboard provides a settings UI at `/api/settings/calendar/*` (SUPER only):
- View today's events
- See current configuration
- Trigger manual sync

## Development

```bash
# Run tests
cd services/calendar-service
PYTHONPATH=src pytest tests/ -v

# Lint
ruff check src/ tests/
ruff format src/ tests/
```

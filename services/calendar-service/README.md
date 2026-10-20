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
| `CALENDAR_API_KEY` | required | Bearer token for protected endpoints |
| `CALENDAR_AUTH_DISABLED` | `false` | Set `true` to disable auth (dev only) |
| `CALENDAR_TOKEN_SECRET` | - | Secret for encrypting OAuth tokens at rest |
| `TELEGRAM_BOT_TOKEN` | required | Telegram bot token |
| `TELEGRAM_CHAT_ID` | required | Chat ID for reminders |
| `GOOGLE_CLIENT_ID` | required | OAuth2 client ID |
| `GOOGLE_CLIENT_SECRET` | required | OAuth2 client secret |
| `CALENDAR_SEED` | `[]` | JSON array of initial calendars |
| `SYNC_INTERVAL_S` | 1800 | Sync interval in seconds (30 min) |
| `DEFAULT_OFFSETS_S` | `[86400,7200,1800]` | Reminder offsets (1d, 2h, 30m) |

### Security Features

**Authentication**: API key authentication is ENABLED by default. Protected endpoints
(`/api/calendar/sync`, `/api/calendar/config`) require a valid bearer token.

```bash
# Production: Set a strong API key
export CALENDAR_API_KEY="your-strong-secret-key"

# Development only: Disable auth explicitly
export CALENDAR_AUTH_DISABLED=true
```

**Token Encryption**: OAuth refresh tokens can be encrypted at rest using Fernet.
If `CALENDAR_TOKEN_SECRET` is set (or `CALENDAR_API_KEY` as fallback), tokens are
stored encrypted. To generate a dedicated secret:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

**Rate Limiting**: All endpoints are rate-limited to prevent abuse:
- Read endpoints (`/upcoming`, `/today`): 60 requests/minute per IP
- Config endpoints (`GET /config`): 30 requests/minute per IP
- Write endpoints (`/sync`, `POST /config`): 10 requests/minute per IP

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

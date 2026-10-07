# portfolio-monitor

Portfolio monitoring service with ETF, crypto staking, and savings tracking.

## Features

- **ETF Monitor**: Yahoo Finance data, technical analysis (MA50/MA200), signals
- **Crypto Monitor**: CoinGecko data, staking APY tracking, Fear & Greed index
- **Savings Monitor**: Bank account tracking with interest projections
- **Email Notifications**: Alert emails for significant changes
- **Scheduled Alerts**: Recurring reminders (contributions, distributions)

## Configuration

Copy `data/settings.example.toml` to `data/settings.toml` and configure your positions.

Environment variables:
- `MONITOR_LANG`: Language (es/en), default: es
- `SMTP_USER`, `SMTP_PASSWORD`: Email notifications
- `COINGECKO_API_KEY`: CoinGecko API key (optional, for higher rate limits)

## API Endpoints

- `GET /api/portfolio/summary` - Full portfolio summary
- `GET /api/portfolio/etf` - ETF positions
- `GET /api/portfolio/crypto` - Crypto staking positions
- `GET /api/portfolio/savings` - Savings accounts
- `GET /api/portfolio/health/external` - External service health checks
- `POST /api/portfolio/refresh` - Trigger manual refresh (rate limited)

## Development

Tests (via dev container):
```bash
# From repo root
.\dev.ps1 ci portfolio-monitor
```

Direct tests:
```bash
cd services/portfolio-monitor
PYTHONPATH=src:../../libs pytest tests/ -v --cov=src --cov-fail-under=80
```

Lint:
```bash
ruff check src/ tests/
ruff format src/ tests/
```

## Architecture

### Design Principles

- **Separation of Concerns**: Monitors, Orchestrator, Config clearly separated
- **Dependency Injection**: `NotifierProtocol`, `MonitorProtocol` for testability
- **Shared Libraries**: Reusable code in `libs/` (http_client, notifications)
- **Externalized i18n**: JSON files in `locales/` (es.json, en.json)

### Current Deployment

- Single-instance deployment on Raspberry Pi
- In-memory rate limiting (sufficient for single instance)
- Internal API only (behind nginx, not exposed publicly)

### Quality Metrics

| Metric | Value | Status |
|--------|-------|--------|
| Test Coverage | 87%+ | ✅ |
| Security (Bandit) | 0 issues | ✅ |
| Lint (Ruff) | Clean | ✅ |
| Tests | 246+ passing | ✅ |

### Shared Libraries Used

| Library | Purpose | Notes |
|---------|---------|-------|
| `libs/http_client/` | HTTP with retry/backoff | Used by crypto_monitor for CoinGecko API |
| `libs/notifications/` | Email sending | Used by email_notifier |

### Future Improvements (when needed)

1. **Distributed Rate Limiting (Redis)**
   - Required if: scaling to multiple instances
   - Implementation: Replace `RateLimiter` class in `routes.py` with Redis-backed sliding window
   - Package: `redis` or `aioredis`

2. **API Authentication**
   - Required if: exposing API publicly
   - Options:
     - OAuth2 with JWT tokens (FastAPI `Depends`)
     - API key authentication
     - Integrate with existing dashboard auth

3. **Template Extraction**
   - Required if: email templates need frequent updates
   - Implementation: Move HTML from `email_notifier.py` to Jinja2 templates
   - Package: `jinja2`

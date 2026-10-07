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
- `CG_API_KEY`: CoinGecko API key (optional, for higher rate limits)

## API Endpoints

- `GET /api/portfolio/summary` - Full portfolio summary
- `GET /api/portfolio/etf` - ETF positions
- `GET /api/portfolio/crypto` - Crypto staking positions
- `GET /api/portfolio/savings` - Savings accounts
- `GET /api/portfolio/health/external` - External service health checks
- `POST /api/portfolio/refresh` - Trigger manual refresh (rate limited)

## Development

Tests:
```bash
cd services/portfolio-monitor
PYTHONPATH=src pytest tests/ -v --cov=src
```

Lint:
```bash
ruff check src/ tests/
ruff format src/ tests/
```

## Architecture Notes

### Current Design

- Single-instance deployment on Raspberry Pi
- In-memory rate limiting (sufficient for single instance)
- Internal API only (behind nginx, not exposed publicly)

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

### Shared Libraries

- `libs/notifications/`: Email sending (used by this service)
- `libs/http_client/`: HTTP client with retry/backoff (available for use)

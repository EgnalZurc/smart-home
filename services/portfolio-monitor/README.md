# portfolio-monitor

Portfolio monitoring service with ETF, crypto staking, and savings tracking.

## Features

- **ETF Monitor**: Yahoo Finance data, technical analysis (MA50/MA200), signals
- **Dividend Calendar**: ETF dividend tracking from Yahoo Finance — trailing-12-month yield, last/estimated-next distribution, estimated annual income, and a 90-day upcoming-payment calendar
- **Crypto Monitor**: CoinGecko data, staking APY tracking, Fear & Greed index
- **Savings Monitor**: Bank account tracking with interest projections
- **DeFi Monitor**: Manual-APY yield tracking for DeFi positions (no external APIs)
- **Rebalance Monitor**: Target-allocation drift detection with suggested trades
- **Email Notifications**: Alert emails for significant changes
- **Scheduled Alerts**: Recurring reminders (contributions, distributions)

## Data Refresh Frequency

| Data Source | Refresh Schedule | Cache TTL |
|-------------|------------------|-----------|
| ETF prices (Yahoo Finance) | Daily at 18:00 (after EU markets close) | 5 min |
| ETF OHLC sparklines | On demand | 15 min |
| Dividend history | On demand | 1 hour |
| Crypto prices (CoinGecko) | Daily at 09:00 | 5 min |
| Fear & Greed Index | Daily at 09:00 | 15 min |
| Savings/DeFi | Instant (local config) | N/A |

Manual refresh: `POST /api/portfolio/refresh` (rate-limited to 1 request per 60s).
Config reload: `POST /api/portfolio/reload-config` (no rate limit).

## Configuration

Copy `settings.example.toml` to `data/settings.toml` and configure your positions.

DeFi positions are tracked under `[[defi]]` blocks. Each block records the
`protocol`, `asset`, deposited `amount` (in EUR), the advertised `apy_pct`, and
an optional `platform_url`. The yield is entered **manually** — there is no
external API integration — and the monitor projects the expected daily, monthly
and yearly yield from those static inputs.

### Rebalance targets

Each ETF (`[[etf.funds]]`) and crypto (`[[crypto.positions]]`) entry accepts an
optional `target_allocation_pct` — the desired weight of that position in the
combined portfolio (ETF + crypto). Targets across all positions should sum to
~100. A position left at `0` (the default) is excluded from rebalance analysis.

The `[rebalance]` section sets `threshold_pct` (default `5.0`): a position is
flagged `needs_rebalance` once the absolute deviation between its current and
target allocation exceeds this many percentage points.

Environment variables:
- `MONITOR_LANG`: Language (es/en), default: es
- `SMTP_USER`, `SMTP_PASSWORD`: Email notifications
- `COINGECKO_API_KEY`: CoinGecko API key (optional, for higher rate limits)

## Security Best Practices

### API Keys and Credentials

This service uses **lazy credential loading** to minimize security exposure:

1. **API keys** (e.g., `COINGECKO_API_KEY`) are read from environment variables at
   request time, not at module load. This:
   - Reduces the window where credentials exist in memory
   - Avoids accidentally logging credentials during import/startup
   - Allows credential rotation without service restart

2. **SMTP credentials** are loaded lazily via properties. The password is fetched
   from the environment only when needed to send an email.

### Recommendations for Operators

- **Never hardcode credentials** in code, Dockerfiles, or docker-compose files
- Use Docker secrets or environment variables injected at runtime
- Rotate credentials periodically (the lazy loading pattern supports this)
- Monitor for credential leaks in logs — credentials should never appear in output
- Use App Passwords (not account passwords) for Gmail SMTP

## API Endpoints

- `GET /api/portfolio/summary` - Full portfolio summary
- `GET /api/portfolio/etf` - ETF positions
- `GET /api/portfolio/crypto` - Crypto staking positions
- `GET /api/portfolio/savings` - Savings accounts
- `GET /api/portfolio/defi` - DeFi yield positions (manual APY, no external APIs)
- `GET /api/portfolio/rebalance` - **Rebalance analysis**: per-position allocation drift vs target + suggested trades
- `GET /api/portfolio/alerts` - Scheduled alerts (upcoming reminders)
- `GET /api/portfolio/alerts/active` - **Active market alerts** for unified dashboard (WARN/DANGER signals + rebalance drift + upcoming dividends within 7 days)
- `GET /api/portfolio/dividends` - **Dividend calendar**: per-ETF trailing yield, last/next distribution, estimated annual income, plus distributions estimated in the next 90 days
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
   - Implementation: Replace the `InMemoryRateLimiter` (from `smart_home_common`, wired in `src/api/routes/helpers.py`) with a Redis-backed sliding window
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

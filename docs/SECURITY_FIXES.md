# Security Fixes Tracking

This document tracks all security issues that have been identified and fixed in the smart-home platform.
The audit system reads this file to avoid re-reporting issues that are already resolved.

## Format

Each entry follows this format:
```
### [SERVICE] Issue Title
- **Severity**: CRITICAL | HIGH | MEDIUM | LOW
- **Status**: FIXED | ACCEPTED_RISK | IN_PROGRESS
- **PR**: #NNN (link to the fix)
- **Fixed Date**: YYYY-MM-DD
- **Description**: What was the issue
- **Fix Applied**: What was done to resolve it
- **Verification**: How to verify it's fixed
```

---

## Fixed Issues

### [dashboard] PC_AGENT_TOKEN Exposure
- **Severity**: CRITICAL
- **Status**: FIXED
- **PR**: #334
- **Fixed Date**: 2026-10-20
- **Description**: PC_AGENT_TOKEN was exposed in logs and error messages
- **Fix Applied**: Token redacted in all log outputs, error messages sanitized
- **Verification**: `grep -r "PC_AGENT_TOKEN" services/dashboard/` returns no plaintext tokens

### [portfolio-monitor] Timing Attack on API Key Comparison
- **Severity**: CRITICAL
- **Status**: FIXED
- **PR**: #335
- **Fixed Date**: 2026-10-20
- **Description**: API key comparison used `==` which is vulnerable to timing attacks
- **Fix Applied**: Changed to `secrets.compare_digest()` for constant-time comparison
- **Verification**: Check `src/main.py` uses `secrets.compare_digest`

### [portfolio-monitor] Ticker Symbol Injection
- **Severity**: CRITICAL
- **Status**: FIXED
- **PR**: #336
- **Fixed Date**: 2026-10-20
- **Description**: Ticker symbols were not validated before use in API calls
- **Fix Applied**: Added regex validation for ticker format, sanitization before external calls
- **Verification**: Test with malicious ticker like `'; DROP TABLE--` should be rejected

### [calendar-service] OAuth PKCE Flow Timing
- **Severity**: CRITICAL
- **Status**: FIXED
- **PR**: #338
- **Fixed Date**: 2026-10-20
- **Description**: OAuth token comparison vulnerable to timing attacks
- **Fix Applied**: Constant-time comparison with `secrets.compare_digest()`
- **Verification**: Check token validation uses constant-time functions

### [presence-service] MQTT Injection
- **Severity**: CRITICAL
- **Status**: FIXED
- **PR**: #340
- **Fixed Date**: 2026-10-20
- **Description**: MQTT topic/payload not sanitized, allowing injection
- **Fix Applied**: Input validation and sanitization for all MQTT messages
- **Verification**: Attempt topic injection with `+/#` wildcards should fail

### [baby-gifts] Token Invitation Logging
- **Severity**: HIGH
- **Status**: FIXED
- **PR**: #339
- **Fixed Date**: 2026-10-20
- **Description**: Invitation tokens were logged in plaintext
- **Fix Applied**: Token redacted in logs, only last 4 chars shown for debugging
- **Verification**: Check logs don't contain full tokens

### [baby-gifts] Gift ID Validation
- **Severity**: HIGH
- **Status**: FIXED
- **PR**: #339
- **Fixed Date**: 2026-10-20
- **Description**: Gift IDs not validated, potential IDOR vulnerability
- **Fix Applied**: UUID validation + ownership check before access
- **Verification**: Attempt to access gift with invalid/other user's ID should 403

### [dashboard] Input Validation
- **Severity**: HIGH
- **Status**: FIXED
- **PR**: #342
- **Fixed Date**: 2026-10-20
- **Description**: User inputs not validated with Pydantic models
- **Fix Applied**: All endpoints now use Pydantic models with validation
- **Verification**: Invalid input returns 422, not 500

### [dashboard] Rate Limiter Memory
- **Severity**: HIGH
- **Status**: FIXED
- **PR**: #342
- **Fixed Date**: 2026-10-20
- **Description**: Rate limiter could grow unbounded, causing memory exhaustion
- **Fix Applied**: LRU eviction with max 10K entries
- **Verification**: Check rate limiter config has `max_size` parameter

### [calendar-service] Auth Disabled by Default
- **Severity**: HIGH
- **Status**: FIXED
- **PR**: #344
- **Fixed Date**: 2026-10-20
- **Description**: Authentication was optional/disabled by default
- **Fix Applied**: Auth enabled by default, explicit opt-out required
- **Verification**: Unauthenticated request returns 401

### [calendar-service] Token Encryption
- **Severity**: HIGH
- **Status**: FIXED
- **PR**: #344
- **Fixed Date**: 2026-10-20
- **Description**: OAuth tokens stored in plaintext
- **Fix Applied**: Fernet encryption for token storage
- **Verification**: Check tokens in storage are encrypted blobs

### [calendar-service] Rate Limiting
- **Severity**: HIGH
- **Status**: FIXED
- **PR**: #344
- **Fixed Date**: 2026-10-20
- **Description**: No rate limiting on API endpoints
- **Fix Applied**: slowapi rate limiter added to all endpoints
- **Verification**: Rapid requests return 429 after threshold

### [portfolio-monitor] API Key Sanitization
- **Severity**: HIGH
- **Status**: FIXED
- **PR**: #347
- **Fixed Date**: 2026-10-20
- **Description**: API keys appeared in logs/errors
- **Fix Applied**: All API keys redacted before logging
- **Verification**: grep logs for API key patterns returns nothing

### [portfolio-monitor] SMTP Password Protection
- **Severity**: HIGH
- **Status**: FIXED
- **PR**: #347
- **Fixed Date**: 2026-10-20
- **Description**: SMTP password could leak in error messages
- **Fix Applied**: Password redacted in all error handling
- **Verification**: SMTP errors don't contain password

### [portfolio-monitor] Circuit Breaker
- **Severity**: HIGH
- **Status**: FIXED
- **PR**: #347
- **Fixed Date**: 2026-10-20
- **Description**: No circuit breaker for external API calls
- **Fix Applied**: Circuit breaker pattern implemented with backoff
- **Verification**: Repeated failures trigger circuit open state

### [portfolio-monitor] Rate Limiting
- **Severity**: HIGH
- **Status**: FIXED
- **PR**: #347
- **Fixed Date**: 2026-10-20
- **Description**: No rate limiting on API endpoints
- **Fix Applied**: slowapi rate limiter added
- **Verification**: Rapid requests return 429

### [ac-service] Rate Limiter Client IP
- **Severity**: HIGH
- **Status**: FIXED
- **PR**: #348
- **Fixed Date**: 2026-10-20
- **Description**: Rate limiter used proxy IP instead of real client IP
- **Fix Applied**: Now reads X-Forwarded-For header for real client IP
- **Verification**: Check rate limiter key_func uses forwarded IP

### [valheim-admin] SSRF Mitigation
- **Severity**: HIGH
- **Status**: FIXED
- **PR**: #350
- **Fixed Date**: 2026-10-20
- **Description**: Server URLs not validated, potential SSRF
- **Fix Applied**: Whitelist of allowed hosts for external connections
- **Verification**: Attempt to connect to internal IP should fail

### [metrics-service] Rate Limiter Memory
- **Severity**: HIGH
- **Status**: FIXED
- **PR**: #351
- **Fixed Date**: 2026-10-20
- **Description**: Rate limiter could exhaust memory
- **Fix Applied**: LRU eviction with bounded size
- **Verification**: Check rate limiter has max entries configured

### [energy-monitor] Rate Limiting
- **Severity**: HIGH
- **Status**: FIXED
- **PR**: #352
- **Fixed Date**: 2026-10-20
- **Description**: No rate limiting on endpoints
- **Fix Applied**: slowapi rate limiter added
- **Verification**: Rapid requests return 429

### [presence-service] MAC Address PII
- **Severity**: HIGH
- **Status**: FIXED
- **PR**: #352
- **Fixed Date**: 2026-10-20
- **Description**: MAC addresses stored/logged in plaintext (PII)
- **Fix Applied**: MAC addresses hashed with SHA256 before storage
- **Verification**: Database/logs contain hashes, not raw MACs

### [casita-suenos] Missing Security Headers
- **Severity**: MEDIUM
- **Status**: FIXED
- **PR**: #TBD
- **Fixed Date**: 2026-10-20
- **Description**: HTTP responses lacked security headers (X-Content-Type-Options, X-Frame-Options, CSP)
- **Fix Applied**: Added security_headers_middleware with X-Content-Type-Options: nosniff, X-Frame-Options: DENY, Content-Security-Policy, X-XSS-Protection, Referrer-Policy
- **Verification**: `curl -I https://raspberrypi.tailaa37cd.ts.net/api/casita/health | grep -E "X-Content|X-Frame|Content-Security"`

### [metrics-service] Missing Security Headers
- **Severity**: MEDIUM
- **Status**: FIXED
- **PR**: #TBD
- **Fixed Date**: 2026-10-20
- **Description**: HTTP responses lacked security headers (X-Content-Type-Options, X-Frame-Options, CSP)
- **Fix Applied**: Added security_headers_middleware with X-Content-Type-Options: nosniff, X-Frame-Options: DENY, Content-Security-Policy, X-XSS-Protection, Referrer-Policy
- **Verification**: `curl -I https://raspberrypi.tailaa37cd.ts.net/api/health/metrics | grep -E "X-Content|X-Frame|Content-Security"`

### [metrics-service] Generic Exception Handling
- **Severity**: MEDIUM
- **Status**: FIXED
- **PR**: #TBD
- **Fixed Date**: 2026-10-20
- **Description**: _db_ok() used `except Exception` which catches too broadly
- **Fix Applied**: Changed to specific exception types (OSError, RuntimeError) for database failures
- **Verification**: Check main.py _db_ok() uses specific exception types

### [metrics-service] Incomplete Logging on Rate Limits
- **Severity**: MEDIUM
- **Status**: FIXED
- **PR**: #TBD
- **Fixed Date**: 2026-10-20
- **Description**: Rate limit violations were not logged, making abuse detection difficult
- **Fix Applied**: Added logging.warning for rate limit hits with client IP and path
- **Verification**: Trigger rate limit and check logs show "Rate limit exceeded for IP"

### [casita-suenos] Generic Exception Handling
- **Severity**: MEDIUM
- **Status**: FIXED
- **PR**: #TBD
- **Fixed Date**: 2026-10-20
- **Description**: Several functions used `except Exception` which catches too broadly
- **Fix Applied**: Replaced with specific exception types (ImportError, ConnectionError, OSError, ValueError, KeyError, TypeError, httpx.TimeoutException, httpx.HTTPError)
- **Verification**: Check main.py for `except Exception` - should only remain in global_exception_handler

### [casita-suenos] Missing/Incomplete Docstrings
- **Severity**: MEDIUM
- **Status**: FIXED
- **PR**: #TBD
- **Fixed Date**: 2026-10-20
- **Description**: Many functions and endpoints lacked comprehensive docstrings
- **Fix Applied**: Added detailed docstrings with Args, Returns, and Raises sections to all public functions and endpoints
- **Verification**: Run `pydoc services/casita-suenos/fase3-app/src/main.py` - all public functions documented

### [casita-suenos] Incomplete Logging
- **Severity**: MEDIUM
- **Status**: FIXED
- **PR**: #TBD
- **Fixed Date**: 2026-10-20
- **Description**: Important operations (rate limit hits, manual triggers, config updates) not logged
- **Fix Applied**: Added logging for rate limit violations, manual trigger invocations, configuration changes, lifecycle events
- **Verification**: Check logs during operation - rate limit hits, manual triggers show in logs

### [energy-monitor] Missing Security Headers
- **Severity**: MEDIUM
- **Status**: FIXED
- **PR**: #TBD
- **Fixed Date**: 2026-10-20
- **Description**: HTTP responses lacked security headers (X-Content-Type-Options, X-Frame-Options, CSP)
- **Fix Applied**: Added security_headers_middleware with X-Content-Type-Options: nosniff, X-Frame-Options: DENY, Content-Security-Policy, X-XSS-Protection, Referrer-Policy
- **Verification**: `curl -I https://raspberrypi.tailaa37cd.ts.net/api/health/energy | grep -E "X-Content|X-Frame|Content-Security"`

### [energy-monitor] Generic Exception Handling
- **Severity**: MEDIUM
- **Status**: FIXED
- **PR**: #TBD
- **Fixed Date**: 2026-10-20
- **Description**: _db_ok() and lifespan used `except Exception` which catches too broadly
- **Fix Applied**: Changed to specific exception types (OSError, RuntimeError) for database/IO failures
- **Verification**: Check main.py _db_ok() and _lifespan() use specific exception types

### [energy-monitor] Incomplete Logging
- **Severity**: MEDIUM
- **Status**: FIXED
- **PR**: #TBD
- **Fixed Date**: 2026-10-20
- **Description**: Rate limit violations and lifecycle events were not logged
- **Fix Applied**: Added logging for rate limit hits with client IP and path, lifecycle start/stop events
- **Verification**: Trigger rate limit and check logs show "Rate limit exceeded for IP"

### [energy-monitor] Missing/Incomplete Docstrings
- **Severity**: MEDIUM
- **Status**: FIXED
- **PR**: #TBD
- **Fixed Date**: 2026-10-20
- **Description**: Functions and endpoints lacked comprehensive docstrings
- **Fix Applied**: Added detailed docstrings with Args, Returns, Raises sections to all public functions and endpoints
- **Verification**: All public functions in main.py have complete docstrings

### [presence-service] Missing Security Headers
- **Severity**: MEDIUM
- **Status**: FIXED
- **PR**: #TBD
- **Fixed Date**: 2026-10-20
- **Description**: HTTP responses lacked security headers (X-Content-Type-Options, X-Frame-Options, CSP)
- **Fix Applied**: Added SecurityHeadersMiddleware with X-Content-Type-Options: nosniff, X-Frame-Options: DENY, Content-Security-Policy, X-XSS-Protection, Referrer-Policy
- **Verification**: `curl -I https://raspberrypi.tailaa37cd.ts.net/api/health/presence | grep -E "X-Content|X-Frame|Content-Security"`

### [presence-service] Generic Exception Handling
- **Severity**: MEDIUM
- **Status**: FIXED
- **PR**: #TBD
- **Fixed Date**: 2026-10-20
- **Description**: database.py db_ok() used `except Exception` which catches too broadly
- **Fix Applied**: Changed to specific exception types (sqlite3.Error, OSError) for database failures
- **Verification**: Check database.py db_ok() uses specific exception types

### [presence-service] Missing/Incomplete Docstrings
- **Severity**: MEDIUM
- **Status**: FIXED
- **PR**: #TBD
- **Fixed Date**: 2026-10-20
- **Description**: Functions, middleware and endpoints lacked comprehensive docstrings
- **Fix Applied**: Added detailed docstrings with Args, Returns, Yields sections to all public functions and endpoints
- **Verification**: All public functions in main.py have complete docstrings with Args/Returns/Yields

### [presence-service] Incomplete Logging
- **Severity**: MEDIUM
- **Status**: FIXED
- **PR**: #TBD
- **Fixed Date**: 2026-10-20
- **Description**: Lifecycle events and health check failures were not logged
- **Fix Applied**: Added logging for startup/shutdown with port info, health check debug logs, and database failure warnings
- **Verification**: Check logs during startup show "Starting presence-service on port 8013..."

### [valheim-admin] Missing Security Headers
- **Severity**: MEDIUM
- **Status**: FIXED
- **PR**: #TBD
- **Fixed Date**: 2026-10-20
- **Description**: HTTP responses lacked security headers (X-Content-Type-Options, X-Frame-Options, CSP)
- **Fix Applied**: Added security_headers_middleware with X-Content-Type-Options: nosniff, X-Frame-Options: DENY, Content-Security-Policy (with unsafe-inline for SPA), X-XSS-Protection, Referrer-Policy
- **Verification**: `curl -I https://raspberrypi.tailaa37cd.ts.net/valheim-admin/health | grep -E "X-Content|X-Frame|Content-Security"`

---

## Accepted Risks

Issues in this section have been evaluated and accepted as low risk given the deployment context.
The audit should NOT re-report these issues.

### [energy-monitor] Shelly HTTP Plaintext
- **Severity**: MEDIUM (downgraded from CRITICAL)
- **Status**: ACCEPTED_RISK
- **Reason**: Shelly devices only communicate on isolated local network (192.168.1.x), never exposed to internet
- **Mitigations**: 
  - Network segmentation (IoT VLAN)
  - Devices not accessible from WAN
  - Traffic stays within Pi's local network
- **Documentation**: Comment added in `shelly_client.py` explaining this is intentional
- **Review Date**: 2026-10-20
- **Next Review**: 2027-04-20 (6 months)

### [presence-service] ARP Spoofing Vulnerability
- **Severity**: MEDIUM (downgraded from CRITICAL)
- **Status**: ACCEPTED_RISK
- **Reason**: ARP spoofing requires physical access to local network; presence detection is informational, not security-critical
- **Mitigations**:
  - Network is WPA3 protected
  - Unknown devices trigger alerts
  - Presence data not used for access control
- **Documentation**: Added to service README
- **Review Date**: 2026-10-20
- **Next Review**: 2027-04-20

### [zigbee2mqtt] Frontend Without auth_token
- **Severity**: HIGH (context: internal only)
- **Status**: ACCEPTED_RISK
- **Reason**: Zigbee2MQTT frontend only accessible via Tailscale VPN, requires authentication at network level
- **Mitigations**:
  - Not exposed to public internet
  - Tailscale requires device authentication
  - nginx doesn't proxy the frontend publicly
- **Documentation**: Added to configuration.example.yaml
- **Review Date**: 2026-10-20
- **Next Review**: 2027-04-20

### [nginx] Hardcoded IP for Open WebUI
- **Severity**: MEDIUM
- **Status**: ACCEPTED_RISK
- **Reason**: Open WebUI runs on EgnalPC (Windows), not in Docker network. DNS resolution not available for external hosts.
- **Mitigations**:
  - IP is static (192.168.1.164)
  - Only accessible via Tailscale
  - Change requires manual nginx reload
- **Documentation**: Comment added in smart-home.conf
- **Review Date**: 2026-10-20
- **Next Review**: 2027-04-20

### [presence-service] Credentials Rotation
- **Severity**: HIGH
- **Status**: ACCEPTED_RISK
- **Reason**: MQTT credentials are service-to-service within Docker network, rotation adds complexity without significant benefit
- **Mitigations**:
  - Credentials in environment variables, not code
  - Docker network isolation
  - Mosquitto requires authentication
- **Documentation**: Added rotation policy comment in config
- **Review Date**: 2026-10-20
- **Next Review**: 2027-04-20

### [casita-suenos] CSRF Protection
- **Severity**: HIGH
- **Status**: FIXED
- **PR**: #365
- **Fixed Date**: 2026-10-20
- **Description**: POST endpoints lacked CSRF protection, vulnerable to cross-site request forgery
- **Fix Applied**: Origin header validation middleware that blocks requests from untrusted origins. Allowed origins: localhost, Tailscale hostname, local network IPs
- **Verification**: `curl -X POST -H "Origin: https://evil.com" https://raspberrypi.tailaa37cd.ts.net/api/casita/run-scraping` should return 403

### [presence-service] NET_RAW Capability
- **Severity**: HIGH
- **Status**: ACCEPTED_RISK
- **Reason**: ARP sweep mode requires NET_RAW capability which expands attack surface, but this is an architectural requirement for raw ARP packet sending to detect devices on local network
- **Mitigations**:
  - Service runs in isolated Docker container
  - Only accessible via Tailscale VPN (not exposed to internet)
  - Alternative SSH-based modes available (openwrt_ssh, fritzbox, mikrotik) that don't require NET_RAW
- **Documentation**: Comment added in `config.py` explaining ROUTER_MODE options
- **Review Date**: 2026-10-21
- **Next Review**: 2027-04-21 (6 months)

### [presence-service] Binding 0.0.0.0
- **Severity**: HIGH
- **Status**: ACCEPTED_RISK
- **Reason**: Service binds to 0.0.0.0 which is required for Docker container networking; the service is only accessible via nginx reverse proxy with authentication
- **Mitigations**:
  - Docker network isolation (smart-home bridge network)
  - nginx auth_request guards all endpoints
  - Tailscale-only external access
- **Documentation**: noqa comment in main.py explaining Docker requirement
- **Review Date**: 2026-10-22
- **Next Review**: 2027-04-22

### [metrics-service] Docker Socket Proxy
- **Severity**: HIGH
- **Status**: ACCEPTED_RISK
- **Reason**: metrics-service uses Docker socket to collect container metrics; this grants container inspection capabilities but the proxy is read-only and the network is isolated
- **Mitigations**:
  - Read-only socket mount (ro flag)
  - Isolated Docker network
  - No write operations exposed
  - Only accessible via authenticated API
- **Documentation**: Comment in docker-compose.prod.yml
- **Review Date**: 2026-10-22
- **Next Review**: 2027-04-22

### [infrastructure] CSP unsafe-inline
- **Severity**: HIGH
- **Status**: ACCEPTED_RISK
- **Reason**: Several SPAs (dashboard, valheim-admin) require unsafe-inline for inline scripts; migrating to nonce-based CSP is a major refactor
- **Mitigations**:
  - All other CSP directives are strict
  - Applications served via Tailscale only
  - nginx includes other security headers (X-Frame-Options, X-Content-Type-Options)
- **Documentation**: Comment in nginx smart-home.conf
- **Review Date**: 2026-10-22
- **Next Review**: 2027-04-22 (consider nonce migration)

### [vaultwarden] Container Runs as Root
- **Severity**: HIGH
- **Status**: IN_PROGRESS
- **Reason**: Official vaultwarden image runs as root by default; adding user: directive requires permission fixes
- **Next Action**: Add `user: "1000:1000"` to docker-compose.prod.yml after verifying data directory permissions
- **Review Date**: 2026-10-22

### [vaultwarden] No Automated Backup
- **Severity**: HIGH
- **Status**: IN_PROGRESS
- **Reason**: Vaultwarden database contains all passwords; manual backup only
- **Next Action**: Create backup script + cron job on Pi
- **Review Date**: 2026-10-22

---

## Fixed Issues (2026-10-22)

### [vacaciones-service] Security Headers Middleware Restored
- **Severity**: HIGH
- **Status**: FIXED
- **PR**: #382
- **Fixed Date**: 2026-10-22
- **Description**: SecurityHeadersMiddleware was accidentally reverted by cross-contamination in PR #376
- **Fix Applied**: Re-added SecurityHeadersMiddleware, rate limit logging, and max_entries=10000 bound
- **Verification**: `curl -I .../api/vacaciones/config | grep -E "X-Content|X-Frame"`

### [calendar-service] Rate Limit Logging
- **Severity**: HIGH
- **Status**: FIXED
- **PR**: #383
- **Fixed Date**: 2026-10-22
- **Description**: Rate limit violations were not logged, making brute-force detection difficult
- **Fix Applied**: Added logger.warning with IP and endpoint when rate limit exceeded
- **Verification**: Trigger rate limit and check logs for "[rate-limit] IP x.x.x.x exceeded limit"

### [dashboard] WebSocket Device Token Fallback
- **Severity**: HIGH
- **Status**: FIXED
- **PR**: #384
- **Fixed Date**: 2026-10-22
- **Description**: WebSocket connections had no fallback auth when JWT expired
- **Fix Applied**: Added device token fallback with IP validation for trusted devices
- **Verification**: Connect WebSocket with expired JWT but valid device token

### [casita-suenos] IMAP Error Sanitization
- **Severity**: HIGH
- **Status**: FIXED
- **PR**: #385
- **Fixed Date**: 2026-10-22
- **Description**: IMAP errors could leak Gmail app password in logs/exceptions
- **Fix Applied**: Added sanitize_imap_error() to redact passwords from all IMAP error messages
- **Verification**: Force IMAP error and check logs for "[REDACTED]" instead of password

### [vaultwarden] File Permissions
- **Severity**: HIGH
- **Status**: FIXED
- **Fixed Date**: 2026-10-22
- **Description**: RSA key and database had world-readable permissions (644)
- **Fix Applied**: `chmod 600` on rsa_key.pem and db.sqlite3 on the Pi
- **Verification**: `ls -la ~/smart-home-prod/data/vaultwarden/` shows -rw------- permissions

---

## Fixed Issues (2026-10-23) - Generic Exception Handling Remediation

All 44 MEDIUM severity issues for generic `except Exception` handling were fixed in PRs #391-#400.
Each service now catches specific exception types appropriate to the operations being performed.

### [casita-suenos] Generic Exception Handling (5 locations)
- **Severity**: MEDIUM
- **Status**: FIXED
- **PR**: #391
- **Fixed Date**: 2026-10-23
- **Description**: Multiple functions used `except Exception` instead of specific types
- **Fix Applied**: Replaced with `imaplib.IMAP4.error`, `httpx.HTTPError`, `httpx.TimeoutException`, `json.JSONDecodeError`, `OSError`, `KeyError`, `ValueError`, `RuntimeError`
- **Verification**: `grep "except Exception" services/casita-suenos/` returns only global_exception_handler

### [dashboard] Generic Exception Handling (3 locations)
- **Severity**: MEDIUM
- **Status**: FIXED
- **PR**: #392
- **Fixed Date**: 2026-10-23
- **Description**: Health check functions used broad exception catching
- **Fix Applied**: Replaced with `httpx.RequestError`, `httpx.HTTPStatusError`, `KeyError`, `OSError`
- **Verification**: Check `dashboard/src/api/health.py` for specific exception types

### [portfolio-monitor] Generic Exception Handling (2 locations)
- **Severity**: MEDIUM
- **Status**: FIXED
- **PR**: #393
- **Fixed Date**: 2026-10-23
- **Description**: API client and notification functions caught all exceptions
- **Fix Applied**: Replaced with `httpx.HTTPError`, `httpx.TimeoutException`, `json.JSONDecodeError`
- **Verification**: Check `services/portfolio-monitor/src/` for specific exception types

### [metrics-service] Generic Exception Handling (2 locations)
- **Severity**: MEDIUM
- **Status**: FIXED
- **PR**: #394
- **Fixed Date**: 2026-10-23
- **Description**: Collector and health check functions used broad catching
- **Fix Applied**: Replaced with `httpx.HTTPError`, `redis.RedisError`, `OSError`
- **Verification**: Check `services/metrics-service/src/` for specific exception types

### [calendar-service] Generic Exception Handling (2 locations)
- **Severity**: MEDIUM
- **Status**: FIXED
- **PR**: #395
- **Fixed Date**: 2026-10-23
- **Description**: iCal parsing and OAuth flow used broad exception catching
- **Fix Applied**: Replaced with `httpx.HTTPError`, `icalendar.ParserError`, `ValueError`
- **Verification**: Check `services/calendar-service/src/` for specific exception types

### [vacaciones-service] Generic Exception Handling (2 locations)
- **Severity**: MEDIUM
- **Status**: FIXED
- **PR**: #396
- **Fixed Date**: 2026-10-23
- **Description**: Holiday lookup functions caught all exceptions
- **Fix Applied**: Replaced with `httpx.HTTPError`, `httpx.TimeoutException`, `json.JSONDecodeError`
- **Verification**: Check `services/vacaciones-service/src/` for specific exception types

### [energy-monitor] Generic Exception Handling (3 locations)
- **Severity**: MEDIUM
- **Status**: FIXED
- **PR**: #397
- **Fixed Date**: 2026-10-23
- **Description**: Shelly client and database functions used broad catching
- **Fix Applied**: Replaced with `httpx.HTTPError`, `httpx.TimeoutException`, `json.JSONDecodeError`, `OSError`
- **Verification**: Check `services/energy-monitor/src/` for specific exception types

### [ac-service] Generic Exception Handling (2 locations)
- **Severity**: MEDIUM
- **Status**: FIXED
- **PR**: #398
- **Fixed Date**: 2026-10-23
- **Description**: AC control API calls caught all exceptions
- **Fix Applied**: Replaced with `httpx.HTTPError`, `httpx.TimeoutException`, `json.JSONDecodeError`
- **Verification**: Check `services/ac-service/src/` for specific exception types

### [baby-gifts] Generic Exception Handling (2 locations)
- **Severity**: MEDIUM
- **Status**: FIXED
- **PR**: #399
- **Fixed Date**: 2026-10-23
- **Description**: Gift API and notification functions used broad catching
- **Fix Applied**: Replaced with `httpx.HTTPError`, `aiohttp.ClientError`, `json.JSONDecodeError`
- **Verification**: Check `services/baby-gifts/src/` for specific exception types

### [libs/smart_home_common] Generic Exception Handling (24 locations)
- **Severity**: MEDIUM
- **Status**: FIXED
- **PR**: #400
- **Fixed Date**: 2026-10-23
- **Description**: Shared libraries (mqtt, redis, http_client, notifications, service_proxy) used broad exception catching
- **Fix Applied**: 
  - MQTT: `(ConnectionError, TimeoutError, OSError)` - note: `paho.mqtt.client.MQTTException` doesn't exist
  - Redis: `redis.RedisError`
  - HTTP: `httpx.HTTPError`, `httpx.TimeoutException`
  - SQLite: `sqlite3.Error`
  - Tests: Changed `raise Exception("...")` to specific types like `raise TimeoutError("...")`
- **Verification**: `grep -r "except Exception" libs/` returns only documented catch-all handlers

---

## Audit Markers

These markers tell the audit system what to skip:

```yaml
# Copy these to .kiro/steering/security-audit-config.md
skip_patterns:
  - "Shelly.*HTTP.*plaintext"  # Accepted: local network only
  - "ARP.*spoof"               # Accepted: network-level mitigation
  - "zigbee2mqtt.*auth_token"  # Accepted: Tailscale-only access
  - "hardcoded.*IP.*Open.?WebUI" # Accepted: external host
  - "MQTT.*credential.*rotation" # Accepted: internal service
  - "MAC.*PII"                 # Fixed: now hashed
  - "timing.*attack.*compare"  # Fixed: secrets.compare_digest
```

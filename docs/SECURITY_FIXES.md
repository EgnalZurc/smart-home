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

### [nginx] postMessage Wildcard Origin (Initial report)
- **Severity**: HIGH
- **Status**: FIXED
- **PR**: #424
- **Fixed Date**: 2026-10-27
- **Description**: sso-cookie-vendor.html used `postMessage(..., '*')` wildcard origin, allowing any site to receive authentication events
- **Fix Applied**: Replaced wildcard `'*'` with explicit trusted origin constant
- **Verification**: Check `infrastructure/nginx/html/sso-cookie-vendor.html` uses `TRUSTED_ORIGIN` constant

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

## Fixed Issues (2026-10-26) - Mosquitto Infrastructure

### [infrastructure/mosquitto] bind_address Documentation
- **Severity**: MEDIUM
- **Status**: FIXED
- **PR**: #TBD
- **Fixed Date**: 2026-10-26
- **Description**: bind_address 127.0.0.1 would break Docker inter-container communication; needed documentation that 0.0.0.0 is intentional
- **Fix Applied**: Changed to 0.0.0.0 with comprehensive SECURITY NOTE explaining why this is safe (Docker network isolation, host firewall, Tailscale ACLs)
- **Verification**: Check `mosquitto.conf` line 26-31 has bind_address 0.0.0.0 with security comment

### [infrastructure/mosquitto] Certificate Renewal Documentation
- **Severity**: MEDIUM
- **Status**: FIXED
- **PR**: #TBD
- **Fixed Date**: 2026-10-26
- **Description**: Server certs valid 365 days vs CA 10 years with no documented renewal procedure
- **Fix Applied**: Added comprehensive CERTIFICATE RENEWAL PROCEDURE section to generate-certs.sh including step-by-step renewal instructions and cron-based expiry monitoring example
- **Verification**: Check `generate-certs.sh` contains "CERTIFICATE RENEWAL PROCEDURE" section

### [infrastructure/mosquitto] require_certificate false Documentation
- **Severity**: LOW
- **Status**: FIXED
- **PR**: #TBD
- **Fixed Date**: 2026-10-26
- **Description**: require_certificate false allows password-only auth; needed documentation that this is intentional
- **Fix Applied**: Added SECURITY NOTE explaining rationale and alternative mTLS configuration
- **Verification**: Check `mosquitto.conf` lines 43-48 has comment explaining require_certificate false

### [infrastructure/mosquitto] RSA Key Size Documentation
- **Severity**: LOW
- **Status**: FIXED
- **PR**: #TBD
- **Fixed Date**: 2026-10-26
- **Description**: RSA 2048-bit used; should document upgrade path to 4096 or ECDSA
- **Fix Applied**: Added TODO comment with upgrade considerations and ECDSA example command
- **Verification**: Check `generate-certs.sh` KEY_SIZE section has TODO and ECDSA example

### [infrastructure/mosquitto] Subscribe/Unsubscribe Logging
- **Severity**: LOW
- **Status**: FIXED
- **PR**: #TBD
- **Fixed Date**: 2026-10-26
- **Description**: Missing log_type subscribe/unsubscribe for audit trail
- **Fix Applied**: Added `log_type subscribe` and `log_type unsubscribe` with explanatory comment
- **Verification**: Check `mosquitto.conf` logging section includes subscribe/unsubscribe

### [infrastructure/mosquitto] TLS Example Version
- **Severity**: LOW
- **Status**: FIXED
- **PR**: #TBD
- **Fixed Date**: 2026-10-26
- **Description**: mosquitto-tls.conf.example showed tlsv1.2; update to tlsv1.3 for consistency
- **Fix Applied**: Changed to tlsv1.3 with comment noting TLS 1.2 fallback option
- **Verification**: Check `mosquitto-tls.conf.example` shows tls_version tlsv1.3

### [infrastructure/mosquitto] Resource Limits Documentation
- **Severity**: LOW
- **Status**: FIXED
- **PR**: #TBD
- **Fixed Date**: 2026-10-26
- **Description**: No max_connections/resource limits configured
- **Fix Applied**: Added TODO section with recommended limits for future scaling
- **Verification**: Check `mosquitto.conf` has "Resource Limits" section with TODO

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
- **Reason**: Several SPAs (ac-service, baby-gifts, portfolio-monitor, valheim-admin, casita-suenos) require unsafe-inline for inline scripts/styles; migrating to nonce-based CSP is a major refactor
- **Mitigations**:
  - All other CSP directives are strict
  - Applications served via Tailscale only
  - nginx auth_request guards all protected endpoints
  - Other security headers (X-Frame-Options, X-Content-Type-Options) remain strict
- **Documentation**: Comment in nginx smart-home.conf and each service's SecurityHeadersMiddleware
- **Review Date**: 2026-10-27
- **Next Review**: 2027-04-27 (consider nonce migration)

#### Migration Roadmap to Nonce-based CSP

The dashboard already uses nonce-based CSP via `CSPNonceMiddleware`. To migrate other services:

**Phase 1 - Assessment (Q1 2027)**
- Audit each SPA for inline scripts/styles usage
- Identify third-party scripts (Chart.js, etc.) that need CDN allowlisting
- Estimate refactoring effort per service

**Phase 2 - Template Services First (Q2 2027)**
- Migrate services with simple SPAs: valheim-admin, casita-suenos
- Pattern: Move inline scripts to external .js files, use nonces for remaining inline
- Validate with CSP Evaluator (https://csp-evaluator.withgoogle.com/)

**Phase 3 - Complex SPAs (Q3 2027)**
- Migrate portfolio-monitor (complex charts), baby-gifts (multiple modals)
- May require build tooling changes to inject nonces into templates

**Phase 4 - Final Services (Q4 2027)**
- Migrate ac-service (real-time WebSocket, Chart.js)
- Remove unsafe-inline from nginx csp-static.conf

**Alternative: Hash-based CSP**
For services with stable inline scripts, CSP hashes ('sha256-...') can replace unsafe-inline without code changes:
1. Generate hashes: `echo -n "script content" | openssl dgst -sha256 -binary | base64`
2. Add to CSP: `script-src 'self' 'sha256-...'`
3. Limitation: Any script change requires CSP update

### [vaultwarden] Container Runs as Root
- **Severity**: HIGH
- **Status**: FIXED
- **PR**: #402
- **Fixed Date**: 2026-10-23
- **Description**: Official vaultwarden image runs as root by default, expanding attack surface
- **Fix Applied**: Added `user: "1000:1000"` to docker-compose.prod.yml
- **Verification**: `docker exec vaultwarden id` shows uid=1000

### [zigbee2mqtt] MQTT Plaintext Connection
- **Severity**: LOW
- **Status**: ACCEPTED_RISK
- **Reason**: MQTT traffic is Docker-internal only (mosquitto container on same bridge network). No traffic leaves the Pi or crosses the internet. TLS would add complexity without security benefit.
- **Mitigations**:
  - Docker bridge network isolation
  - MQTT authentication required (mosquitto `allow_anonymous false`)
  - No external exposure
- **Documentation**: Comment added in `configuration.example.yaml` explaining rationale
- **Review Date**: 2026-10-26
- **Next Review**: 2027-04-26 (6 months)

### [zigbee2mqtt] MQTT Plaintext Connection
- **Severity**: LOW
- **Status**: ACCEPTED_RISK
- **Reason**: MQTT traffic is Docker-internal only (mosquitto container on same bridge network). No traffic leaves the Pi or crosses the internet. TLS would add complexity without security benefit.
- **Mitigations**:
  - Docker bridge network isolation
  - MQTT authentication required (mosquitto `allow_anonymous false`)
  - No external exposure
- **Documentation**: Comment added in `configuration.example.yaml` explaining rationale
- **Review Date**: 2026-10-26
- **Next Review**: 2027-04-26 (6 months)

### [vaultwarden] No Automated Backup
- **Severity**: HIGH
- **Status**: FIXED
- **PR**: #403
- **Fixed Date**: 2026-10-23
- **Description**: Vaultwarden database contains all passwords; manual backup only
- **Fix Applied**: Created `scripts/backup-vaultwarden.sh` with:
  - Online/hot backup using sqlite3 .backup (no downtime)
  - RSA key backup (critical for decryption)
  - 7-day rotation
  - Checksum manifest
  - Dry-run mode
- **Setup**: SCP to Pi, chmod +x, add to crontab: `0 3 * * * /home/pi/scripts/backup-vaultwarden.sh`
- **Verification**: Run `./backup-vaultwarden.sh --dry-run` on Pi

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

## Fixed Issues (2026-10-26)

### [zigbee2mqtt] Frontend Binding to 0.0.0.0
- **Severity**: MEDIUM
- **Status**: FIXED
- **PR**: #TBD
- **Fixed Date**: 2026-10-26
- **Description**: Frontend bound to 0.0.0.0 by default, potentially exposing it directly if firewall/Docker network is misconfigured
- **Fix Applied**: Added `host: 127.0.0.1` to bind only to localhost; frontend accessed via nginx reverse proxy
- **Verification**: Check `configuration.example.yaml` has `host: 127.0.0.1` under `frontend:`

### [zigbee2mqtt] Empty Z2M_FRONTEND_PASSWORD Documentation
- **Severity**: MEDIUM
- **Status**: FIXED
- **PR**: #TBD
- **Fixed Date**: 2026-10-26
- **Description**: If Z2M_FRONTEND_PASSWORD env var is empty, frontend has no token protection (not documented)
- **Fix Applied**: Added comment documenting this as accepted risk (nginx auth_request still protects /zigbee/ path)
- **Verification**: Check `configuration.example.yaml` has comment about empty password behavior

### [zigbee2mqtt] Duplicate YAML Block
- **Severity**: LOW
- **Status**: FIXED
- **PR**: #TBD
- **Fixed Date**: 2026-10-26
- **Description**: Lines 49-57 were a copy-paste duplicate of the advanced block (cache_state, last_seen, devices, version)
- **Fix Applied**: Removed the duplicate lines
- **Verification**: `wc -l configuration.example.yaml` should be ~74 lines (was ~83 with duplicate)

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

## LOW Severity Issues - Review (2026-10-23)

### ACCEPTED_RISK (architectural requirements or acceptable tradeoffs)

| Issue | Service | Reason | Mitigations |
|-------|---------|--------|-------------|
| `0.0.0.0` binding | All services | Required for Docker container networking | nginx reverse proxy + Tailscale + auth_request |
| apr_md5_crypt hash | dashboard | Required for nginx .htpasswd compatibility | File not exposed externally; sessions use JWT |
| HTTP plaintext Shelly | energy-monitor | IoT devices on isolated local network | Network segmentation; not internet-accessible |
| ARP spoofing | presence-service | Presence is informational, not security-critical | WPA3; alerts on unknown devices |
| Legacy plaintext tokens | calendar-service | Migration path for existing tokens | Encryption enabled for new tokens; migration in progress |

### ACCEPTABLE (low risk, no fix needed)

| Issue | Service | Reason |
|-------|---------|--------|
| Session timeout 24h | dashboard | Reasonable TTL; device tokens provide graceful renewal |
| Test credentials | tests/* | Test-only secrets like "test-secret-key-32-chars" - not in production |
| Dockerfiles | all | Follow best practices (multi-stage, non-root, healthcheck) |
| Error detail | all | Messages are generic ("Not ready", "Timeout") without internal paths |

### LOW - Potential future improvements

| Issue | Service | Current State | Recommendation |
|-------|---------|---------------|----------------|
| CSP unsafe-inline | casita, valheim-admin, portfolio, baby-gifts, ac-service | Inline scripts need unsafe-inline | See Migration Roadmap above |
| No request ID logging | some services | Requests not correlated across services | Add X-Request-ID header propagation |
| Limited audit logging | all | Basic logging, no security-specific audit trail | Consider structured audit logging for sensitive operations |
| In-memory rate limiters | all services | Rate limits not shared across instances | See Redis evaluation below |

### Rate Limiter Architecture Evaluation (2026-10-27)

**Current State**: All services use `InMemoryRateLimiter` from `smart_home_common`:
- Thread-safe with LRU eviction (max 10K entries)
- Per-instance state (not shared across replicas)
- Zero external dependencies

**Redis-backed Alternative**: slowapi with Redis storage (already used by calendar-service and energy-monitor for basic rate limiting via slowapi)

**Evaluation**:

| Factor | In-Memory | Redis-backed |
|--------|-----------|--------------|
| Complexity | Simple, no infra | Requires Redis container |
| Latency | ~0.1ms | ~1-5ms per check |
| Multi-instance | ❌ Each instance has own state | ✅ Shared state |
| Failure mode | Graceful (limits per-instance) | Redis down = limits fail |
| Memory | Per-process (~50KB at max) | Centralized |

**Decision**: **Keep in-memory rate limiters**

Rationale:
1. **Single-instance deployment**: All services run as single containers on Pi 5. Multi-instance coordination is not needed.
2. **Tailscale-only access**: Attack surface is limited to authenticated Tailscale users, not open internet.
3. **Simplicity**: No Redis dependency to maintain, monitor, or recover from failures.
4. **Defense-in-depth**: nginx also has `limit_req` zones for auth and general traffic.

**When to reconsider**:
- If services scale to multiple replicas
- If public internet exposure is added
- If coordinated rate limiting across services is needed

**Review Date**: 2026-10-27
**Next Review**: 2027-04-27

---

## Fixed Issues (2026-10-23) - LOW Severity Code Quality Improvements

All 96 LOW severity issues were fixed in PRs #410-#422 (13 PRs total).
These are code quality improvements: type hints, documentation, constants extraction, and security config documentation.

### Batch 1: Core Services (39 LOW - PRs #410-#413)

#### [presence-service] Code Quality (11 issues)
- **PR**: #410
- **Changes**: Type hints with TYPE_CHECKING pattern, docstrings with Raises sections, GDPR Art. 6(1)(f) comments for IP logging

#### [dashboard] Code Quality (10 issues)
- **PR**: #413
- **Changes**: Type hints for health check functions, docstrings with Args/Returns/Raises, documentation for WebSocket auth flow

#### [ac-service] Code Quality (10 issues)
- **PR**: #412
- **Changes**: Type hints, magic numbers extracted to constants (TEMP_MIN=16, TEMP_MAX=30), docstrings with exception documentation

#### [calendar-service] Code Quality (8 issues)
- **PR**: #411
- **Changes**: Type hints, dead code removed, docstrings for OAuth flow, test coverage TODOs

### Batch 2: Secondary Services (29 LOW - PRs #414-#417)

#### [metrics-service] Code Quality (7 issues)
- **PR**: #414
- **Changes**: Type hints with TYPE_CHECKING, docstrings with Raises sections, documentation for rate limiter config

#### [vacaciones-service] Code Quality (8 issues)
- **PR**: #415
- **Changes**: Error handling in _serve_html, GDPR comments for IP logging, CSP documentation

#### [baby-gifts-service] Code Quality (7 issues)
- **PR**: #416
- **Changes**: Constants extracted (MAX_NAME_LENGTH, MAX_GIFT_AMOUNT), GDPR comments, test coverage TODOs

#### [casita-suenos] Code Quality (7 issues)
- **PR**: #417
- **Changes**: Lambdas replaced with explicit code, dead code removed, string check fix ("b" -> "búsqueda")

### Batch 3: Remaining Services (20 LOW - PRs #418-#421)

#### [valheim-admin] Code Quality (5 issues)
- **PR**: #418
- **Changes**: New README.md documenting Docker socket requirements and security considerations

#### [vaultwarden] Code Quality (3 issues)
- **PR**: #419
- **Changes**: Base image pinned to specific version, README expanded with backup/restore procedures

#### [energy-monitor] Code Quality (6 issues)
- **PR**: #420
- **Changes**: Improved encapsulation in alerts.py, new tests for alert thresholds, documentation

#### [portfolio-monitor] Code Quality (6 issues)
- **PR**: #421
- **Changes**: New README.md, improved type hints in monitors/, new tests for savings_monitor

### Batch 4: Infrastructure (8 LOW - PR #422)

#### [infrastructure/nginx] Security Configuration Documentation
- **PR**: #422
- **Changes**:
  - TLS cipher suite rationale documented (AEAD-only, PFS via ECDHE/DHE)
  - Elliptic curve choices explained (X25519 primary, secp384r1 fallback)
  - Session caching and ticket configuration documented
  - Security headers (HSTS, CSP, X-Frame-Options) rationale added
  - Rate limiting parameters documented

### Summary

| Batch | Services | Issues | PRs |
|-------|----------|--------|-----|
| 1 | presence, dashboard, ac, calendar | 39 | #410-#413 |
| 2 | metrics, vacaciones, baby-gifts, casita | 29 | #414-#417 |
| 3 | valheim-admin, vaultwarden, energy, portfolio | 20 | #418-#421 |
| 4 | infrastructure/nginx | 8 | #422 |
| **Total** | **13 services** | **96** | **13 PRs** |

---

## Fixed Issues (2026-10-26/27) - Security Audit Wave

Full security audit conducted on 2026-10-26, fixes implemented and deployed 2026-10-27.
**15 PRs merged** covering 2 HIGH, ~25 MEDIUM, and ~50 LOW severity issues.

### HIGH Severity Fixes

#### [nginx] postMessage Wildcard Origin
- **Severity**: HIGH
- **Status**: FIXED
- **PR**: #424
- **Fixed Date**: 2026-10-27
- **Description**: sso-cookie-vendor.html used `postMessage(..., '*')` wildcard origin, allowing any site to receive authentication events
- **Fix Applied**: Replaced wildcard `'*'` with explicit trusted origin constant `TRUSTED_ORIGIN`
- **Verification**: Check `infrastructure/nginx/html/sso-cookie-vendor.html`

#### [presence-service] Rate Limiting on Health Endpoints
- **Severity**: HIGH
- **Status**: FIXED
- **PR**: #426
- **Fixed Date**: 2026-10-27
- **Description**: Health endpoints had no rate limiting, potential DoS vector
- **Fix Applied**: Added rate limiting (30 req/min) to health endpoints using InMemoryRateLimiter
- **Verification**: Rapid requests to `/health` return 429 after threshold

### MEDIUM Severity Fixes

#### [ac-service] CORS Origins Validation
- **Severity**: MEDIUM
- **Status**: FIXED
- **PR**: #427
- **Fixed Date**: 2026-10-27
- **Description**: CORS origins not validated, MQTT timeout not documented
- **Fix Applied**: Added CORS origin validation, documented MQTT connection timeouts
- **Verification**: Check `services/ac-service/src/main.py` CORS middleware

#### [dashboard] Async Endpoint Consistency
- **Severity**: MEDIUM
- **Status**: FIXED
- **PR**: #428
- **Fixed Date**: 2026-10-27
- **Description**: Mixed async/sync patterns, generic exception handling
- **Fix Applied**: Standardized async endpoints, improved exception handling with specific types
- **Verification**: Check `dashboard/src/api/` for consistent async patterns

#### [vacaciones] DOM XSS Prevention
- **Severity**: MEDIUM
- **Status**: FIXED
- **PR**: #429
- **Fixed Date**: 2026-10-27
- **Description**: User input rendered without escaping, potential DOM XSS
- **Fix Applied**: Added `escapeHtml()` function, applied to all user input renders, documented X-Forwarded-For trust
- **Verification**: Check templates for escapeHtml usage

#### [baby-gifts] Security Headers & GDPR
- **Severity**: MEDIUM
- **Status**: FIXED
- **PR**: #430
- **Fixed Date**: 2026-10-27
- **Description**: Missing security headers, no GDPR documentation for IP logging, sqlite without timeout
- **Fix Applied**: Added SecurityHeadersMiddleware, GDPR Art. 6(1)(f) comments, sqlite3.connect with timeout=5.0
- **Verification**: Check response headers include X-Content-Type-Options, X-Frame-Options

#### [portfolio-monitor] Origin Validation & Sanitization
- **Severity**: MEDIUM
- **Status**: FIXED
- **PR**: #431
- **Fixed Date**: 2026-10-27
- **Description**: Origin validation weak, position_id/account_id not sanitized
- **Fix Applied**: Improved Origin validation with Sec-Fetch-Mode, sanitized IDs, added MonitorName enum type hint
- **Verification**: Check `services/portfolio-monitor/src/api/` for sanitization

#### [casita-suenos] Rate Limiting for Dismiss/Undismiss
- **Severity**: MEDIUM
- **Status**: FIXED
- **PR**: #432
- **Fixed Date**: 2026-10-27
- **Description**: Dismiss/undismiss endpoints had no rate limiting
- **Fix Applied**: Added rate limiting to dismiss/undismiss endpoints, documented Telegram token handling
- **Verification**: Check `/api/casita/dismiss` and `/api/casita/undismiss` have rate limiting

#### [metrics-service] Code Cleanup
- **Severity**: LOW
- **Status**: FIXED
- **PR**: #433
- **Fixed Date**: 2026-10-27
- **Description**: Duplicate import, hardcoded Spanish strings
- **Fix Applied**: Removed duplicate `time` import, added TODO(i18n) comments for Spanish strings
- **Verification**: `ruff check services/metrics-service/src/`

#### [valheim-admin] Rate Limiter & Endpoints
- **Severity**: MEDIUM
- **Status**: FIXED
- **PR**: #434
- **Fixed Date**: 2026-10-27
- **Description**: Rate limiter unbounded, missing endpoints, hardcoded password
- **Fix Applied**: Rate limiter with max_entries=10000, implemented /api/worlds/upload and /api/network endpoints, removed hardcoded password
- **Verification**: Check `services/valheim-admin/src/main.py`

#### [energy-monitor] Code Quality
- **Severity**: MEDIUM/LOW
- **Status**: FIXED
- **PR**: #435
- **Fixed Date**: 2026-10-27
- **Description**: Missing __all__ exports, Protocol typing, daily budget edge case
- **Fix Applied**: Added __all__ exports, Protocol typing for dependencies, edge case handling
- **Verification**: Check `services/energy-monitor/src/` for __all__ definitions

#### [calendar-service] Seed Validation & Tests
- **Severity**: MEDIUM
- **Status**: FIXED
- **PR**: #436
- **Fixed Date**: 2026-10-27
- **Description**: Missing seed validation, exception handling gaps, low test coverage
- **Fix Applied**: Added seed validation, improved exception handling, added database tests
- **Verification**: Run `pytest services/calendar-service/tests/`

### Infrastructure Fixes

#### [vaultwarden] Documentation
- **Severity**: LOW
- **Status**: FIXED
- **PR**: #437
- **Fixed Date**: 2026-10-27
- **Description**: LOG_LEVEL and EXPOSE 3012 not documented
- **Fix Applied**: Documented LOG_LEVEL tradeoffs (warn vs info), explained WebSocket port 3012 usage
- **Verification**: Check `services/vaultwarden/Dockerfile` comments

#### [zigbee2mqtt] Security Hardening
- **Severity**: MEDIUM
- **Status**: FIXED
- **PR**: #438
- **Fixed Date**: 2026-10-27
- **Description**: Frontend binding, duplicate YAML entries, plaintext MQTT connection
- **Fix Applied**: Changed frontend host to localhost, cleaned up duplicate config, documented MQTT plaintext as ACCEPTED_RISK (Docker-internal only)
- **Verification**: Check `infrastructure/zigbee2mqtt/config/configuration.example.yaml`

#### [mosquitto] Security Documentation
- **Severity**: MEDIUM
- **Status**: FIXED
- **PR**: #439
- **Fixed Date**: 2026-10-27
- **Description**: Missing TLS documentation, no cert renewal procedure, bind address not restricted
- **Fix Applied**: Added TLS setup documentation, cert renewal procedure in comments, documented bind address rationale
- **Verification**: Check `infrastructure/mosquitto/` for README and config comments

### Summary (2026-10-26/27 Audit)

| Severity | Count | PRs |
|----------|-------|-----|
| HIGH | 2 | #424, #426 |
| MEDIUM | ~25 | #427-#436, #438-#439 |
| LOW | ~50 | Included in above PRs |
| **Total** | **~77** | **15 PRs (#424, #426-#439)** |

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


---

## Fixed Issues (2026-10-28) - LOW Severity Audit + Production Fixes

Audit conducted 2026-10-28 identified ~178 LOW severity issues across all services.
13 PRs merged (#455-#468) fixing code quality: type hints, magic numbers, docstrings, constants, exports.
2 additional PRs (#469-#470) fixed post-deploy production issues.

### LOW Severity Fixes - Code Quality

#### [casita-suenos] Type Hints, Magic Numbers, Docstrings
- **Severity**: LOW
- **PR**: #455
- **Fixed Date**: 2026-10-28
- **Description**: Missing type hints, undocumented magic numbers, incomplete docstrings
- **Fix Applied**: Added type hints with TYPE_CHECKING pattern, extracted magic numbers to named constants, added comprehensive docstrings with Args/Returns/Raises sections
- **Verification**: `ruff check services/casita-suenos/` passes

#### [portfolio-monitor] TTL Cache Constants, Middleware Typing
- **Severity**: LOW
- **PR**: #457
- **Fixed Date**: 2026-10-28
- **Description**: Hard-coded TTL values, missing type hints in middleware
- **Fix Applied**: Extracted TTL constants (CACHE_TTL_SECONDS), added type hints to middleware functions
- **Verification**: Check `services/portfolio-monitor/src/` for CACHE_TTL_* constants

#### [vacaciones-service] Return Type Annotations, Comments
- **Severity**: LOW
- **PR**: #458
- **Fixed Date**: 2026-10-28
- **Description**: Missing return type annotations, insufficient code comments
- **Fix Applied**: Added return type annotations to all public functions, added explanatory comments
- **Verification**: Check function signatures include `-> ReturnType`

#### [metrics-service] Literal Types, Constants
- **Severity**: LOW
- **PR**: #459
- **Fixed Date**: 2026-10-28
- **Description**: Magic numbers, missing Literal type hints for known string values
- **Fix Applied**: Added BYTES_PER_MB constant, Literal type hints for status strings
- **Verification**: Check `services/metrics-service/src/` for BYTES_PER_MB

#### [valheim-admin] JS Constants, Middleware Typing
- **Severity**: LOW
- **PR**: #461
- **Fixed Date**: 2026-10-28
- **Description**: Hard-coded values in JavaScript, missing Python type hints
- **Fix Applied**: Extracted JS constants, added Python middleware type hints
- **Verification**: Check `services/valheim-admin/src/static/` for const declarations

#### [presence-service] Constants, Exports
- **Severity**: LOW
- **PR**: #462
- **Fixed Date**: 2026-10-28
- **Description**: Magic number for MAC hash length, missing __all__ exports
- **Fix Applied**: Added MAC_HASH_LENGTH constant, __all__ exports in modules
- **Verification**: Check for `MAC_HASH_LENGTH = 64` constant

#### [dashboard] System Stats Constants, Exports
- **Severity**: LOW
- **PR**: #464
- **Fixed Date**: 2026-10-28
- **Description**: Magic numbers in system stats, missing __all__ exports
- **Fix Applied**: Added KB, GB, CPU_SAMPLE_DELAY constants after imports, __all__ exports
- **Verification**: Check `dashboard/src/system/stats.py` for KB/GB constants

#### [energy-monitor] Rate Limit Constants
- **Severity**: LOW
- **PR**: #465
- **Fixed Date**: 2026-10-28
- **Description**: Hard-coded rate limit retry-after value
- **Fix Applied**: Added RATE_LIMIT_RETRY_AFTER_S constant
- **Verification**: Check for `RATE_LIMIT_RETRY_AFTER_S` constant

#### [nginx] Security Headers
- **Severity**: LOW
- **PR**: #466
- **Fixed Date**: 2026-10-28
- **Description**: Missing COOP, CORP, X-DNS-Prefetch-Control headers
- **Fix Applied**: Added Cross-Origin-Opener-Policy, Cross-Origin-Resource-Policy, X-DNS-Prefetch-Control headers to security-headers.conf
- **Verification**: `curl -I ... | grep -E "Cross-Origin|DNS-Prefetch"`

#### [baby-gifts] Database Constants
- **Severity**: LOW
- **PR**: #467
- **Fixed Date**: 2026-10-28
- **Description**: Hard-coded database timeout, user token prefix
- **Fix Applied**: Added DB_TIMEOUT_SECONDS, USER_TOKEN_PREFIX constants
- **Verification**: Check for `DB_TIMEOUT_SECONDS = 5.0` constant

#### [calendar-service] Time Constants
- **Severity**: LOW
- **PR**: #468
- **Fixed Date**: 2026-10-28
- **Description**: Hard-coded time values, magic numbers for token length
- **Fix Applied**: Added time constants, MIN_OAUTH_TOKEN_LENGTH constant
- **Verification**: Check for time-related constants in config

### Production Fixes (Post-Deploy)

#### [nginx] Health Endpoint Rate Limit Burst
- **Severity**: PRODUCTION
- **PR**: #469
- **Fixed Date**: 2026-10-28
- **Description**: Dashboard loads ~12 health checks simultaneously on page load; with burst=5 and rate=20r/s, requests were getting 429 Too Many Requests errors
- **Fix Applied**: Increased burst from 5 to 20 for all health endpoints in smart-home.conf
- **Verification**: Load dashboard and verify no 429 errors on health checks

#### [dashboard] CSP Script Hash Mismatch
- **Severity**: PRODUCTION
- **PR**: #470
- **Fixed Date**: 2026-10-28
- **Description**: CSP was blocking inline script with error "sha256-6aocxNIG1gKbasSx4jiZ2r+1Xt9RspymZv1XK5UIwpU= not in script-src". The hash in csp_nonce.py was outdated after recent changes to dashboard.html
- **Fix Applied**: Updated SHA256 hash in csp_nonce.py to match current dashboard.html inline script content
- **Verification**: Dashboard loads without CSP violations in browser console

### Summary (2026-10-28)

| Category | Count | PRs |
|----------|-------|-----|
| LOW (code quality) | ~50 | #455, #457-#459, #461-#462, #464-#468 |
| Production fixes | 2 | #469-#470 |
| **Total** | **~52** | **13 PRs** |

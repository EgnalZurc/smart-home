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

---

## In Progress

### [casita-suenos] CSRF Protection
- **Severity**: HIGH
- **Status**: IN_PROGRESS
- **PR**: Pending (tests need update)
- **Description**: POST endpoints lack CSRF protection
- **Fix Applied**: CSRF middleware added, but existing tests don't send X-CSRF-Token header
- **Blocker**: Tests need to be updated to include CSRF tokens
- **Assigned**: Next audit cycle

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

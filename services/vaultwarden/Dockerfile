# Vaultwarden — Self-hosted Bitwarden-compatible password manager
# Wrapper image with environment pre-configured for Cuchi Casa deployment
#
# Base: vaultwarden/server:1.37.4 (official image, Debian-based)
# Customization: Environment variables baked in for subpath deployment
#
# ADMIN_TOKEN is NOT included here — passed via runtime secret
FROM vaultwarden/server:1.37.4@sha256:efb3cde962015fcc036b2ea625242248611943b27212ebf4392841fb30fad055

# Timezone
ENV TZ=Europe/Madrid

# Vaultwarden configuration
ENV DOMAIN=https://raspberrypi.tailaa37cd.ts.net/passwords
ENV WEBSOCKET_ENABLED=true
ENV SIGNUPS_ALLOWED=false
ENV LOG_LEVEL=warn

# Rocket (web server) configuration
ENV ROCKET_PROFILE=release
ENV ROCKET_ADDRESS=0.0.0.0
ENV ROCKET_PORT=80

# Health check - verifies API is responding, not just port open
# /passwords/alive returns JSON: {"alive": true, "timestamp": "2026-10-23T12:00:00Z"}
# Success: HTTP 200 with valid JSON indicates full API readiness
# Failure: Non-200 status or connection refused triggers container restart
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -sf http://localhost:80/passwords/alive || exit 1

EXPOSE 80 3012

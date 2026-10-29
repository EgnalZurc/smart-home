# Vaultwarden — Self-hosted Bitwarden-compatible password manager
# Wrapper image with environment pre-configured for Cuchi Casa deployment
#
# Base: vaultwarden/server:1.37.4 (official image, Debian-based)
# Customization: Environment variables baked in for subpath deployment
#
# ADMIN_TOKEN is NOT included here — passed via runtime secret
#
# UPDATE PROCEDURE (base image pinned by digest for reproducibility):
# 1. Check for new releases: https://github.com/dani-garcia/vaultwarden/releases
# 2. Update tag and digest: docker pull vaultwarden/server:<new_tag>
#    then: docker inspect --format='{{index .RepoDigests 0}}' vaultwarden/server:<new_tag>
# 3. Test locally before deploying to production
# 4. Review changelog for breaking changes or new environment variables
FROM vaultwarden/server:1.37.4@sha256:efb3cde962015fcc036b2ea625242248611943b27212ebf4392841fb30fad055

# Timezone
ENV TZ=Europe/Madrid

# Vaultwarden configuration
ENV DOMAIN=https://raspberrypi.tailaa37cd.ts.net/passwords
ENV WEBSOCKET_ENABLED=true
ENV SIGNUPS_ALLOWED=false
# LOG_LEVEL tradeoff:
# - warn: Reduces noise, only shows warnings and errors. Good for production.
# - info: Includes request logs and startup info. Useful for debugging.
# - debug/trace: Very verbose, generates large logs. Only for troubleshooting.
# Current choice: 'warn' to minimize disk usage on Pi SD card while still
# catching important issues. Change to 'info' temporarily when debugging.
ENV LOG_LEVEL=warn

# Rocket (web server) configuration
ENV ROCKET_PROFILE=release
ENV ROCKET_ADDRESS=0.0.0.0
ENV ROCKET_PORT=80

# Health check - verifies API is responding, not just port open
# /passwords/alive returns JSON: {"alive": true, "timestamp": "2026-10-23T12:00:00Z"}
# Success: HTTP 200 with valid JSON indicates full API readiness
# Failure: Non-200 status or connection refused triggers container restart
#
# curl flags explained:
#   -s (silent): Suppress progress output, keeps logs clean
#   -f (fail): Exit with code 22 on HTTP errors (4xx/5xx), not just connection failures
#      Without -f, curl returns 0 even for HTTP 500, masking server errors
#      TLS errors still surface as non-zero exit codes (curl code 60 for cert issues)
HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 \
    CMD curl -sf http://localhost:80/passwords/alive || exit 1

# Exposed ports:
# - 80: Main HTTP API and web vault interface (Rocket server)
# - 3012: WebSocket notifications (WEBSOCKET_ENABLED=true above)
#   WebSocket enables real-time sync across browser extensions and mobile apps
#   without requiring constant polling. Removes significant load from the server.
#   If you disable WEBSOCKET_ENABLED, port 3012 becomes unused but harmless.
EXPOSE 80 3012

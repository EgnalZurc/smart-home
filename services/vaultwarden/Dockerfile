# Vaultwarden — Self-hosted Bitwarden-compatible password manager
# Wrapper image with environment pre-configured for Cuchi Casa deployment
#
# Base: vaultwarden/server:latest (official image)
# Customization: Environment variables baked in for subpath deployment
#
# ADMIN_TOKEN is NOT included here — passed via runtime secret
# hadolint ignore=DL3007
FROM vaultwarden/server:latest

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

# Health check
HEALTHCHECK --interval=60s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -sf http://localhost:80/passwords/ || exit 1

EXPOSE 80 3012

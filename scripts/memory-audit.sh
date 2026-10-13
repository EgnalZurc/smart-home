#!/bin/bash
# memory-audit.sh — Daily memory audit for smart-home containers
# Collects docker stats and POSTs to the dashboard monitoring endpoint.
# 
# Install in crontab:
#   0 3 * * * /home/pi/projects/smart-home/scripts/memory-audit.sh >> /var/log/memory-audit.log 2>&1
#
# Dependencies: jq, curl, docker

set -euo pipefail

DASHBOARD_URL="${DASHBOARD_URL:-http://smart-home-backend:8080}"
ENDPOINT="${DASHBOARD_URL}/api/monitoring/memory/snapshot"

# Get timestamp in ISO format
TIMESTAMP=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

# Collect docker stats (no-stream = single snapshot)
# Format: container_name, mem_usage (bytes), mem_limit (bytes), mem_percent
STATS_RAW=$(docker stats --no-stream --format '{{.Name}}\t{{.MemUsage}}\t{{.MemPerc}}' 2>/dev/null || true)

if [ -z "$STATS_RAW" ]; then
    echo "[$(date)] ERROR: No containers running or docker stats failed"
    exit 1
fi

# Parse stats into JSON array
# MemUsage format: "47.2MiB / 96MiB" or "1.2GiB / 2GiB"
STATS_JSON="[]"

while IFS=$'\t' read -r name mem_usage mem_percent; do
    # Skip empty lines
    [ -z "$name" ] && continue
    
    # Extract used and limit from "47.2MiB / 96MiB"
    used_raw=$(echo "$mem_usage" | cut -d'/' -f1 | tr -d ' ')
    limit_raw=$(echo "$mem_usage" | cut -d'/' -f2 | tr -d ' ')
    
    # Convert to MiB
    convert_to_mib() {
        local val="$1"
        local num=$(echo "$val" | sed 's/[^0-9.]//g')
        if echo "$val" | grep -qi 'gib'; then
            echo "$num * 1024" | bc
        elif echo "$val" | grep -qi 'kib'; then
            echo "scale=2; $num / 1024" | bc
        else
            # Assume MiB
            echo "$num"
        fi
    }
    
    used_mib=$(convert_to_mib "$used_raw")
    limit_mib=$(convert_to_mib "$limit_raw")
    
    # Extract percent (remove % sign)
    percent=$(echo "$mem_percent" | tr -d '%')
    
    # Build JSON object for this container
    CONTAINER_JSON=$(jq -n \
        --arg container "$name" \
        --argjson used_mib "$used_mib" \
        --argjson limit_mib "$limit_mib" \
        --argjson percent "$percent" \
        '{container: $container, used_mib: $used_mib, limit_mib: $limit_mib, percent: $percent}')
    
    # Append to array
    STATS_JSON=$(echo "$STATS_JSON" | jq --argjson obj "$CONTAINER_JSON" '. + [$obj]')
    
done <<< "$STATS_RAW"

# Build final payload
PAYLOAD=$(jq -n \
    --arg timestamp "$TIMESTAMP" \
    --argjson stats "$STATS_JSON" \
    '{timestamp: $timestamp, stats: $stats}')

echo "[$(date)] Sending memory snapshot with $(echo "$STATS_JSON" | jq length) containers"

# POST to dashboard
RESPONSE=$(curl -s -w "\n%{http_code}" -X POST \
    -H "Content-Type: application/json" \
    -d "$PAYLOAD" \
    "$ENDPOINT" 2>&1)

HTTP_CODE=$(echo "$RESPONSE" | tail -n1)
BODY=$(echo "$RESPONSE" | sed '$d')

if [ "$HTTP_CODE" = "200" ]; then
    ALERTS=$(echo "$BODY" | jq -r '.alerts | length')
    echo "[$(date)] OK: Snapshot received, $ALERTS alerts"
    
    # Log any alerts
    if [ "$ALERTS" -gt 0 ]; then
        echo "[$(date)] ALERTS:"
        echo "$BODY" | jq -r '.alerts[] | "  - \(.container): \(.percent)% (\(.used_mib)MiB / \(.limit_mib)MiB)"'
    fi
else
    echo "[$(date)] ERROR: HTTP $HTTP_CODE - $BODY"
    exit 1
fi

# Smart Home Platform - Requirements

**Last updated**: July 23, 2026
**Platform**: Raspberry Pi 5 (4GB RAM) - self-hosted home automation

---

## Architecture Summary

- **Backend**: Python 3.12 + FastAPI (per app)
- **MQTT Broker**: Eclipse Mosquitto
- **Zigbee**: Zigbee2MQTT with Ember (EZSP) coordinator
- **Frontend**: HTML + vanilla JS modules + Tailwind CSS v4 (compiled, tools/rebuild-css.sh)
- **Deployment**: Docker Compose
- **Public Access**: Tailscale Funnel -> https://raspberrypi.tailaa37cd.ts.net
- **Hardware**: Raspberry Pi 5 4GB, 5x SONOFF SNZB-02D, Mitsubishi AC (MELCloud), 2x WD 500GB HDD USB

---

## Dev Notes

- **Encoding**: Files with emojis/non-ASCII MUST be written on Pi via Python utf-8. Never scp from PowerShell.
- **Tailwind rebuild**: Run `bash tools/rebuild-css.sh` after adding new Tailwind classes.
- Rate limiting: auth 60 req/min (login), general 20 req/s (app), /static/ no limit.
- Zigbee sensors: report every 1h or on change >0.1C; timeout 3600s.
- MELCloud credentials required in .env (Device ID + Building ID).
- HYSTERESIS_ON=0.1 set in .env (modulating starts at target+0.1?C, not default +0.5?C).
- AC virtual sensor ("AC" key in history): MELCloud room temp, excluded from Zigbee averages.

---

# PROJECT: Smart Home Platform (Dashboard + Routing)

## DASH-1 - Platform Dashboard  Complete

| # | Requirement | Status |
|---|---|---|
| DASH-1 | /smart-home renders a dashboard | Complete |
| DASH-1.1 | Mobile-first, modern, minimalist - no emojis in title | Complete |
| DASH-1.2 | Title: Cuchi Casa | Complete |
| DASH-1.3 | Language selector (ES/EN), Spanish default | Complete |
| DASH-1.4 | All text translatable, self-contained T={} object | Complete |
| DASH-1.5 | App registry (APPS array) - only registered apps shown | Complete |
| DASH-1.6 | AC Control registered and displayed | Complete |
| DASH-1.6b | Zigbee2MQTT registered and displayed; click redirects to /zigbee/ | Complete |
| DASH-1.7 | No placeholder cards | Complete |
| DASH-1.8 | Live status dot per app card (skipped for apps without a status endpoint) | Complete |
| DASH-1.9 | Loading spinner until translations + status loaded | Complete |
| Tests | test_dash_routing.py - 25 tests | Complete |

## DASH-2 - Root Redirect  Complete

| # | Requirement | Status |
|---|---|---|
| DASH-2 | GET / returns 301 permanent redirect to /smart-home | Complete |
| Tests | test_root_redirects_to_smart_home, test_redirect_is_permanent | Complete |

## DASH-3 - Default Language  Complete

| # | Requirement | Status |
|---|---|---|
| DASH-3 | Default language is Spanish for all apps | Complete |
| DASH-3.1 | Dashboard defaults to Spanish (no cookie) | Complete |
| DASH-3.2 | AC app defaults to Spanish (i18n.js default locale = es) | Complete |
| DASH-3.3 | Shared cookie across apps | Complete |

---

# PROJECT: AC Control App

## AC-CORE - Core AC Control  Complete

| # | Requirement | Status |
|---|---|---|
| AC-CORE | AC app at /smart-home/ac controls Mitsubishi AC via MELCloud | Complete |
| AC-CORE.1 | Temperature display from Zigbee sensors (5x SONOFF SNZB-02D) | Complete |
| AC-CORE.2 | Average temperature calculated from active Zigbee sensors only (AC virtual sensor excluded) | Complete |
| AC-CORE.3 | Outdoor temperature from Open-Meteo API | Complete |
| AC-CORE.4 | Real AC state fetched from MELCloud every 30s | Complete |
| Tests | test_routes.py (18), test_ac_controller.py (20), test_mqtt_handler.py (17), test_melcloud_client.py (9) | Complete |

## AC-CHART - Dynamic Sensor Chart  Complete

| # | Requirement | Status |
|---|---|---|
| AC-CHART | Single dynamic chart replacing the two static graphs | Complete |
| AC-CHART.1 | Tab selector: Temperature / Humidity | Complete |
| AC-CHART.2 | Toggle chip per source (avg + A/C + each sensor); default = avg only | Complete |
| AC-CHART.3 | Chips show colored glowing dot; active = colored border + glow, inactive = dimmed | Complete |
| AC-CHART.4 | Time range picker (segmented control): 1h, 6h, 12h, 24h (default), 48h, 7d | Complete |
| AC-CHART.5 | Chart fetches /api/sensors/history?start=X&end=Y for the selected range | Complete |
| AC-CHART.6 | One colored line per active source, own legend (Chart.js legend hidden) | Complete |
| AC-CHART.7 | Gaussian smoothing + time-bucket averaging (bucket size scales with range) | Complete |
| AC-CHART.8 | "No data" message when selected range has no readings | Complete |
| AC-CHART.9 | All labels translatable ES/EN | Complete |
| AC-CHART.10 | AC room temp recorded hourly (at :00) by AcTempScheduler into history JSON | Complete |
| AC-CHART.11 | AC shown as dashed line from historical data; flat ref fallback if no history yet | Complete |
| AC-CHART.12 | Mean / min / max values shown below chart for current range | Complete |
| Tests | test_mqtt_handler.py (record_ac_temp), test_routes.py (history range), test_ac_temp_scheduler.py (5) | Complete |

## AC-AUTO - Automatic Control  Complete

| # | Requirement | Status |
|---|---|---|
| AC-AUTO | Controller loop runs every 10s evaluating sensor average vs target temperature | Complete |
| AC-AUTO.1 | States: off, cooling_max, modulating, cooldown, manual, system_off, error | Complete |
| AC-AUTO.2 | OFF -> COOLING_MAX when avg > target + hysteresis_on (default +0.5?C) | Complete |
| AC-AUTO.3 | COOLING_MAX -> MODULATING when avg enters (cold_threshold, hot_threshold] | Complete |
| AC-AUTO.4 | COOLING_MAX / MODULATING -> COOLDOWN when avg < target - hysteresis_off (default -0.3?C) | Complete |
| AC-AUTO.5 | COOLDOWN waits cooldown_seconds (default 180s) before re-evaluating | Complete |
| AC-AUTO.6 | MODULATING uses proportional setpoint: hot edge=min_setpoint (19?C), cold edge=max_setpoint (30?C) | Complete |
| AC-AUTO.7 | Hysteresis band: hot_threshold = target + 0.5, cold_threshold = target - 0.3 (configurable) | Complete |
| AC-AUTO.8 | Sensor timeout (3600s) - sensor marked inactive if no recent data | Complete |
| AC-AUTO.9 | No active sensors in COOLING_MAX: keeps COOLING_MAX (last known hot, stays on) | Complete |
| AC-AUTO.10 | No active sensors in MODULATING: keeps last setpoint until sensors recover | Complete |
| Tests | test_f0_ac_auto_control.py (5), test_state_machine.py (23) | Complete |

## AC-MANUAL - Manual Mode  Complete

| # | Requirement | Status |
|---|---|---|
| AC-MANUAL | Manual mode overrides automatic control | Complete |
| AC-MANUAL.1 | Set target temperature, fan speed, AC mode (cool/heat/fan/dry/auto) | Complete |
| AC-MANUAL.2 | Manual commands queued and sent to MELCloud | Complete |
| AC-MANUAL.3 | Pending command icon shown while command awaits AC confirmation | Complete |
| AC-MANUAL.4 | Pending icon disappears once AC confirms the new state | Complete |
| AC-MANUAL.5 | All actions show a toast confirming what was done | Complete |
| AC-MANUAL.6 | UI reflects only persisted server state (no optimistic updates); updates on next poll (~5s) | Complete |
| AC-MANUAL.7 | While a command is in-flight, the affected control shows a pending state (amber sweep animation, non-interactive) until the next poll confirms the change | Complete |
| Tests | test_f0_manual_mode.py - 16 tests (TestF0ManualMode, TestNoOptimisticUI, TestPendingStateFeedback) | Complete |

## AC-ERR - Error Tracking  Complete

| # | Requirement | Status |
|---|---|---|
| AC-ERR | Error tracker collects warnings/errors from all components | Complete |
| AC-ERR.1 | Errors surfaced in UI (error panel with dismiss) | Complete |
| AC-ERR.2 | MELCloud auth failures tracked | Complete |
| AC-ERR.3 | Sensor timeouts tracked | Complete |
| AC-ERR.4 | Outdoor API failures tracked | Complete |
| Tests | test_f0_error_tracking.py (5), test_error_tracker.py (12) | Complete |

## AC-STATE - State Persistence  Complete

| # | Requirement | Status |
|---|---|---|
| AC-STATE | Controller state persisted to disk, restored on restart | Complete |
| AC-STATE.1 | Minimizes unnecessary AC restarts after container restart | Complete |
| Tests | test_state_persistence.py (5) | Complete |

## AC-I18N - Internationalization  Complete

| # | Requirement | Status |
|---|---|---|
| AC-I18N | AC app supports Spanish (default) and English | Complete |
| AC-I18N.1 | Language selector in header, flag icons | Complete |
| AC-I18N.2 | Locale cookie shared with dashboard | Complete |
| Tests | test_dash_routing.py (cookie sharing tests) | Complete |

## AC-NAV - Navigation  Complete

| # | Requirement | Status |
|---|---|---|
| AC-NAV | Home button in AC app header navigates to /smart-home | Complete |
| AC-NAV.1 | Non-intrusive, house icon, between status and language selector | Complete |

## AC-URL - App URL Migration  Complete

| # | Requirement | Status |
|---|---|---|
| AC-URL | AC app served at /smart-home/ac | Complete |
| AC-URL.1 | All /api/ endpoints unchanged | Complete |
| AC-URL.2 | /zigbee/ unchanged | Complete |
| Tests | test_ac_app_route_in_main, test_api_paths_unchanged, test_static_paths_absolute | Complete |

---

# PROJECT: Photo Backup (Immich)

## PHO-0 - Infrastructure Setup  Complete

| # | Requirement | Status |
|---|---|---|
| PHO-0 | Both external HDDs formatted ext4 and mounted | Complete |
| PHO-0.1 | WD 2TB (sda) ext4, label: immich-data, mounted at /mnt/immich (1.7TB free) ? primary storage | Complete |
| PHO-0.2 | /mnt/immich in fstab with nofail,noatime | Complete |
| PHO-0.3 | Directories: library/, upload/, thumbs/, profile/, backups/ created on /mnt/immich | Complete |
| PHO-0.4 | WD 500GB (sdb) ext4, label: immich-backup, mounted at /mnt/immich-backup (435GB free) ? backup | Complete |
| PHO-0.5 | /mnt/immich-backup in fstab with nofail,noatime | Complete |
| PHO-0.6 | If primary fills up: 500GB can be repurposed as additional primary storage | Planned |

## PHO-1 - Immich Deployment  In Progress

| # | Requirement | Priority | Status |
|---|---|---|---|
| PHO-1 | Deploy Immich via Docker Compose, /mnt/immich as storage | HIGH | Complete |
| PHO-1.1 | Accessible at /photos (nginx proxy + sub_filter rewrite) | HIGH | Complete |
| PHO-1.2 | ML container disabled at deploy (profiles: [ml], not started by default) | HIGH | Complete |
| PHO-1.3 | Video transcoding: H.265 for space efficiency | MEDIUM | Planned |
| PHO-1.4 | Transcoding only at night | MEDIUM | Planned |
| PHO-1.5 | Two accounts: egnal and virchu | HIGH | Pending manual setup |
| PHO-1.6 | Dashboard card (Photos app registered in APPS array) | MEDIUM | Complete |

## PHO-2 - Mobile App & Backup  Planned (after PHO-1)

| # | Requirement | Priority | Status |
|---|---|---|---|
| PHO-2 | Immich Android app on both phones | HIGH | Planned |
| PHO-2.1 | Auto-backup on home WiFi | HIGH | Planned |
| PHO-2.2 | Free Up Space feature | HIGH | Planned |
| PHO-2.3 | Remote access via Tailscale | HIGH | Planned |

## PHO-3 - Google Photos Migration  Planned (after PHO-2)

| # | Requirement | Priority | Status |
|---|---|---|---|
| PHO-3 | Migrate Google Photos to Immich | MEDIUM | Planned |
| PHO-3.1 | Export via Google Takeout | MEDIUM | Planned |
| PHO-3.2 | Import via immich-go CLI | MEDIUM | Planned |
| PHO-3.3 | Verify before deleting from Google | HIGH | Planned |

## PHO-4 - Backup Redundancy  In Progress

| # | Requirement | Priority | Status |
|---|---|---|---|
| PHO-4 | Second HDD as nightly backup | MEDIUM | In Progress |
| PHO-4.1 | rsync /mnt/immich -> /mnt/immich-backup (excludes postgres dir) | MEDIUM | Complete |
| PHO-4.2 | Cron at 03:00 daily (/usr/local/bin/immich-backup.sh) | MEDIUM | Complete |
| PHO-4.3 | Backup log at /var/log/immich-backup.log | LOW | Complete |
| PHO-4.4 | Postgres database backup (pg_dump nightly) | MEDIUM | Planned |

---

# PROJECT: Humidifier Decision (Seasonal Study)

## HUM-0 - Seasonal Humidity Study  Complete

| # | Requirement | Status |
|---|---|---|
| HUM-0 | Collect hourly humidity samples, consolidated into daily snapshots indefinitely | Complete |
| HUM-0.1 | Each daily snapshot tagged with season (spring/summer/autumn/winter) | Complete |
| HUM-0.2 | Data kept permanently - builds seasonal picture across multiple years | Complete |
| HUM-0.3 | GET /api/humidity/study returns per-season analysis and recommendations | Complete |
| HUM-0.4 | Recommendation per season: recommended / not_needed / insufficient_data / no_data | Complete |
| HUM-0.5 | Season computed from date: DJF=winter, MAM=spring, JJA=summer, SON=autumn | Complete |
| HUM-0.6 | Min 7 days per season required before giving a definitive recommendation | Complete |
| HUM-0.7 | Migration: old snapshots without season field get it auto-assigned on read | Complete |
| HUM-0.8 | UI shows 4 seasonal cards with mean, fraction below 40%, signal days count | Complete |
| HUM-0.9 | UI shows last 14 daily entries with season icon and key metrics | Complete |
| Tests | test_humidity_analysis.py - 28 tests (TestGetSeason, TestCollectSample, TestBuildDailySnapshot, TestAppendSnapshot, TestSeasonSummary, TestGetSummary) | Complete |

**Current data**: 21 days of summer 2026 (2026-07-02 to 2026-07-22). Summer result: humidifier recommended (14/21 signal days).

## HUM-1 - Humidifier Control  Pending seasonal data

| # | Requirement | Priority | Status |
|---|---|---|---|
| HUM-1 | Humidifier on/off, target range 40-55% | MEDIUM | Pending seasonal data |
| HUM-1.1 | Use existing Zigbee sensors | MEDIUM | Pending seasonal data |
| HUM-1.2 | Zigbee smart plug for humidifier control | MEDIUM | Pending seasonal data |
| HUM-1.3 | Configurable thresholds | MEDIUM | Pending seasonal data |
| HUM-1.4 | On/off hysteresis | MEDIUM | Pending seasonal data |
| HUM-1.5 | State machine integration | LOW | Pending seasonal data |

**Decision gate**: Implement HUM-1 when at least 2 seasons show "recommended". Currently: 1/4 (summer only).

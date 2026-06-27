# Smart Home Platform - Requirements

**Last updated**: June 26, 2026 (aligned)
**Platform**: Raspberry Pi 5 (4GB RAM) � self-hosted home automation

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
- Windows serial bridge: serial_bridge.py exposes COM3 via TCP port 8282.
- MELCloud credentials required in .env (Device ID + Building ID).

---

# PROJECT: Smart Home Platform (Dashboard + Routing)

## DASH-1 � Platform Dashboard  ? Complete

| # | Requirement | Status |
|---|---|---|
| DASH-1 | /smart-home renders a dashboard | Complete |
| DASH-1.1 | Mobile-first, modern, minimalist � no emojis in title | Complete |
| DASH-1.2 | Title: Cuchi Casa | Complete |
| DASH-1.3 | Language selector (ES/EN), Spanish default | Complete |
| DASH-1.4 | All text translatable, self-contained T={} object | Complete |
| DASH-1.5 | App registry (APPS array) � only registered apps shown | Complete |
| DASH-1.6 | AC Control registered and displayed | Complete |
| DASH-1.6b | Zigbee2MQTT registered and displayed; click redirects to /zigbee/ | Complete |
| DASH-1.7 | No placeholder cards | Complete |
| DASH-1.8 | Live status dot per app card | Complete |
| DASH-1.9 | Loading spinner until translations + status loaded | Complete |
| Tests | test_dash_routing.py � 20 tests covering all DASH-1 requirements | Complete |

## DASH-2 � Root Redirect  ? Complete

| # | Requirement | Status |
|---|---|---|
| DASH-2 | GET / returns 301 permanent redirect to /smart-home | Complete |
| Tests | test_root_redirects_to_smart_home, test_redirect_is_permanent | Complete |

## DASH-3 � Default Language  ? Complete

| # | Requirement | Status |
|---|---|---|
| DASH-3 | Default language is Spanish for all apps | Complete |
| DASH-3.1 | Dashboard defaults to Spanish (no cookie) | Complete |
| DASH-3.2 | AC app defaults to Spanish (i18n.js default locale = es) | Complete |
| DASH-3.3 | Shared cookie across apps | Complete |

---

# PROJECT: AC Control App

## AC-CORE ? Core AC Control  ? Complete

| # | Requirement | Status |
|---|---|---|
| AC-CORE | AC app at /smart-home/ac controls Mitsubishi AC via MELCloud | Complete |
| AC-CORE.1 | Temperature display from Zigbee sensors (5x SONOFF SNZB-02D) | Complete |
| AC-CORE.2 | Average temperature calculated from active sensors | Complete |
| AC-CORE.3 | Outdoor temperature from Open-Meteo API | Complete |
| AC-CORE.4 | Real AC state fetched from MELCloud every 30s | Complete |
| Tests | test_routes.py, test_ac_controller.py, test_mqtt_handler.py, test_melcloud_client.py | Complete |

## AC-CHART — Dynamic Sensor Chart  ✅ Complete

| # | Requirement | Status |
|---|---|---|
| AC-CHART | Single dynamic chart replacing the two static graphs | Complete |
| AC-CHART.1 | Tab selector: Temperature / Humidity | Complete |
| AC-CHART.2 | Toggle chip per source (avg + A/C + each sensor); default = avg only | Complete |
| AC-CHART.3 | Chips show colored glowing dot; active = colored border + glow, inactive = dimmed | Complete |
| AC-CHART.4 | Time range picker (segmented control): 1h, 6h, 12h, 24h (default), 48h, 7d | Complete |
| AC-CHART.5 | Chart fetches /api/sensors/history?start=X&end=Y for the selected range | Complete |
| AC-CHART.6 | One colored line per active source, Chart.js legend hidden (own legend) | Complete |
| AC-CHART.7 | Gaussian smoothing + time-bucket averaging (bucket size scales with range) | Complete |
| AC-CHART.8 | "No data" message when selected range has no readings | Complete |
| AC-CHART.9 | All labels translatable ES/EN (range buttons, tabs, average, no-data) | Complete |
| AC-CHART.10 | AC room temp recorded hourly (at :00) by AcTempScheduler into history JSON | Complete |
| AC-CHART.11 | AC shown as dashed line from historical data; flat ref fallback if no history | Complete |
| AC-CHART.12 | Mean / min / max values shown below chart for current range | Complete |
| Tests | test_mqtt_handler.py (record_ac_temp, AC disk load), test_routes.py (history range) | Complete |

## AC-AUTO ? Automatic Control  ? Complete

| # | Requirement | Status |
|---|---|---|
| AC-AUTO | Controller loop runs every 10s evaluating sensor average vs target | Complete |
| AC-AUTO.1 | State machine: idle, cooling_max, cooling_mid, modulating, forced_on | Complete |
| AC-AUTO.2 | Hysteresis on/off to prevent rapid switching | Complete |
| AC-AUTO.3 | Cooldown period between state transitions | Complete |
| AC-AUTO.4 | Sensor timeout (3600s) ? sensor marked inactive if no data | Complete |
| AC-AUTO.5 | Falls back to forced_on if all sensors time out | Complete |
| Tests | test_f0_ac_auto_control.py ? integration tests, test_state_machine.py | Complete |

## AC-MANUAL ? Manual Mode  ? Complete

| # | Requirement | Status |
|---|---|---|
| AC-MANUAL | Manual mode overrides automatic control | Complete |
| AC-MANUAL.1 | Set target temperature, fan speed, AC mode (cool/heat/fan/dry/auto) | Complete |
| AC-MANUAL.2 | Manual commands queued and sent to MELCloud | Complete |
| AC-MANUAL.3 | Pending command icon shown while command awaits AC confirmation | Complete |
| AC-MANUAL.4 | Pending icon disappears once AC confirms the new state | Complete |
| Tests | test_f0_manual_mode.py ? integration tests | Complete |

## AC-ERR ? Error Tracking  ? Complete

| # | Requirement | Status |
|---|---|---|
| AC-ERR | Error tracker collects warnings/errors from all components | Complete |
| AC-ERR.1 | Errors surfaced in UI (error panel with dismiss) | Complete |
| AC-ERR.2 | MELCloud auth failures tracked | Complete |
| AC-ERR.3 | Sensor timeouts tracked | Complete |
| AC-ERR.4 | Outdoor API failures tracked | Complete |
| Tests | test_f0_error_tracking.py, test_error_tracker.py | Complete |

## AC-STATE ? State Persistence  ? Complete

| # | Requirement | Status |
|---|---|---|
| AC-STATE | Controller state persisted to disk, restored on restart | Complete |
| AC-STATE.1 | Minimizes unnecessary AC restarts after container restart | Complete |
| Tests | test_state_persistence.py | Complete |

## AC-I18N ? Internationalization  ? Complete

| # | Requirement | Status |
|---|---|---|
| AC-I18N | AC app supports Spanish (default) and English | Complete |
| AC-I18N.1 | Language selector in header, flag icons | Complete |
| AC-I18N.2 | Locale cookie shared with dashboard | Complete |
| Tests | test_dash_routing.py (cookie sharing tests) | Complete |


## AC-NAV � Navigation  ? Complete

| # | Requirement | Status |
|---|---|---|
| AC-NAV | Home button in AC app header navigates to /smart-home | Complete |
| AC-NAV.1 | Non-intrusive, house icon, between status and language selector | Complete |

## AC-URL � App URL Migration  ? Complete

| # | Requirement | Status |
|---|---|---|
| AC-URL | AC app served at /smart-home/ac | Complete |
| AC-URL.1 | All /api/ endpoints unchanged | Complete |
| AC-URL.2 | /zigbee/ unchanged | Complete |
| Tests | test_ac_app_route_in_main, test_api_paths_unchanged, test_static_paths_absolute | Complete |

---

# PROJECT: Photo Backup (Immich)

## PHO-0 � Infrastructure Setup  ? Complete

| # | Requirement | Status |
|---|---|---|
| PHO-0 | External HDD formatted and mounted | Complete |
| PHO-0.1 | WD 500GB ext4, label: immich-data | Complete |
| PHO-0.2 | Mounted at /mnt/immich, fstab nofail | Complete |
| PHO-0.3 | Directories: library/, upload/, thumbs/, profile/, backups/ | Complete |
| PHO-0.4 | Second HDD reserved for backup | Planned |

## PHO-1 � Immich Deployment  ?? Planned

| # | Requirement | Priority | Status |
|---|---|---|---|
| PHO-1 | Deploy Immich via Docker Compose, /mnt/immich as storage | HIGH | Planned |
| PHO-1.1 | Accessible at /photos | HIGH | Planned |
| PHO-1.2 | ML disabled at deploy, schedulable at night | HIGH | Planned |
| PHO-1.3 | Video transcoding: H.265 for space efficiency | MEDIUM | Planned |
| PHO-1.4 | Transcoding only at night | MEDIUM | Planned |
| PHO-1.5 | Two accounts: egnal and virchu | HIGH | Planned |
| PHO-1.6 | Dashboard card when deployed | MEDIUM | Planned |

## PHO-2 � Mobile App & Backup  ?? Planned (after PHO-1)

| # | Requirement | Priority | Status |
|---|---|---|---|
| PHO-2 | Immich Android app on both phones | HIGH | Planned |
| PHO-2.1 | Auto-backup on home WiFi | HIGH | Planned |
| PHO-2.2 | Free Up Space feature | HIGH | Planned |
| PHO-2.3 | Remote access via Tailscale | HIGH | Planned |

## PHO-3 � Google Photos Migration  ?? Planned (after PHO-2)

| # | Requirement | Priority | Status |
|---|---|---|---|
| PHO-3 | Migrate Google Photos to Immich | MEDIUM | Planned |
| PHO-3.1 | Export via Google Takeout | MEDIUM | Planned |
| PHO-3.2 | Import via immich-go CLI | MEDIUM | Planned |
| PHO-3.3 | Verify before deleting from Google | HIGH | Planned |

## PHO-4 � Backup Redundancy  ?? Planned (after PHO-1)

| # | Requirement | Priority | Status |
|---|---|---|---|
| PHO-4 | Second HDD as nightly backup | MEDIUM | Planned |
| PHO-4.1 | Daily rsync /mnt/immich -> /mnt/immich-backup | MEDIUM | Planned |
| PHO-4.2 | Night schedule | MEDIUM | Planned |
| PHO-4.3 | Backup status in dashboard/error tracker | LOW | Planned |

---

# PROJECT: Humidity Study (Humidifier Decision)

## HUM-0 � Data Collection  ?? In progress (ends ~17 Jul 2026)

| # | Requirement | Status |
|---|---|---|
| HUM-0 | Collect hourly humidity data for 3 weeks | In progress |
| HUM-0.1 | Hourly samples + daily 24h snapshots | Complete |
| HUM-0.2 | GET /api/humidity/study | Complete |
| HUM-0.3 | Decision gate ~17 Jul 2026 | Planned |
| Tests | test_humidity_analysis.py � 17 tests | Complete |

**Decision**: Implement humidifier if signal=YES on 13+/21 days.

## HUM-1 � Humidifier Control  ? Pending analysis result

| # | Requirement | Priority | Status |
|---|---|---|---|
| HUM-1 | Humidifier on/off, 40-55% range | MEDIUM | Pending analysis |
| HUM-1.1 | Use existing sensors | MEDIUM | Pending analysis |
| HUM-1.2 | Zigbee smart plug | MEDIUM | Pending analysis |
| HUM-1.3 | Configurable thresholds | MEDIUM | Pending analysis |
| HUM-1.4 | On/off hysteresis | MEDIUM | Pending analysis |
| HUM-1.5 | State machine integration | LOW | Pending analysis |

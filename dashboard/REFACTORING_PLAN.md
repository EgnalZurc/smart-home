# Dashboard Architecture Refactoring Plan

## Current State Analysis

### File Size Distribution (Lines of Code)
| File | Lines | Status |
|------|-------|--------|
| api/routes.py | 1421 | ❌ Too large - needs splitting |
| controllers/ac_controller.py | 601 | ⚠️ Large but cohesive |
| api/auth_routes.py | 600 | ⚠️ Large - consider splitting |
| user_profiles.py | 557 | ⚠️ Large but cohesive |
| controllers/state_machine.py | 343 | ✅ OK |
| auth_users.py | 303 | ✅ OK |
| main.py | 268 | ✅ OK |
| Others | <260 | ✅ OK |

### Security Analysis (Bandit)
- No medium/high severity issues
- 97 low severity (mostly hardcoded strings, acceptable)
- One nosec annotation for parameterized SQL (auth_users.py:226)

## Identified Issues

### 1. routes.py (1421 lines) - Critical
Contains 10 different tag groups that should be separate files:
- Health checks (15 endpoints)
- Casita proxy (10 endpoints)
- Container control (3 endpoints)
- System stats (1 endpoint)
- AC proxy (15 endpoints)
- Vacaciones proxy (5 endpoints)
- Baby Gifts proxy (15 endpoints)
- Portfolio proxy (10 endpoints)
- PC control (3 endpoints)
- External API proxies (flood, firms)

### 2. auth_routes.py (600 lines)
Mixed concerns:
- Login/logout flow
- Trust request management
- Admin user CRUD
- Admin profile CRUD
- Session verification

### 3. user_profiles.py (557 lines)
- Database schema + migrations
- Profile CRUD
- User-profile assignments
- Permission logic
- App registry

## Proposed New Structure

```
dashboard/src/
├── api/
│   ├── __init__.py
│   ├── router.py              # Main router that includes all sub-routers
│   ├── health.py              # Health check endpoints (NEW)
│   ├── auth/
│   │   ├── __init__.py
│   │   ├── routes.py          # Login/logout, /me, verify
│   │   ├── trust.py           # Trust request management (NEW)
│   │   └── admin.py           # Admin CRUD for users/profiles (NEW)
│   └── proxy/
│       ├── __init__.py
│       ├── casita.py          # Casita Sueños proxy (NEW)
│       ├── ac.py              # AC service proxy (NEW)
│       ├── vacaciones.py      # Vacaciones proxy (NEW)
│       ├── baby_gifts.py      # Baby Gifts proxy (NEW)
│       ├── portfolio.py       # Portfolio proxy (NEW)
│       ├── external.py        # Flood/FIRMS APIs (NEW)
│       └── pc.py              # PC control proxy (NEW)
├── system/
│   ├── __init__.py
│   ├── containers.py          # Container management (from routes.py)
│   └── stats.py               # System stats (from routes.py)
├── profiles/
│   ├── __init__.py
│   ├── models.py              # Profile dataclasses, constants (NEW)
│   ├── db.py                  # Database operations (NEW)
│   ├── permissions.py         # Permission logic (NEW)
│   └── migrations.py          # Schema migrations (NEW)
├── auth/
│   ├── __init__.py            # Re-export main functions
│   ├── jwt.py                 # JWT creation/validation (from auth.py)
│   ├── users.py               # User store (from auth_users.py)
│   └── devices.py             # Device tokens (from auth_devices.py)
├── controllers/               # Keep as-is, cohesive
│   ├── __init__.py
│   ├── ac_controller.py
│   ├── state_machine.py
│   └── vacaciones_controller.py
├── sensors/
│   ├── __init__.py
│   ├── mqtt.py                # MQTT handler (from mqtt_handler.py)
│   └── scheduler.py           # AC temp scheduler
└── services/
    ├── __init__.py
    ├── melcloud.py            # MELCloud client
    ├── zigbee.py              # Zigbee2MQTT client
    └── subscriptions.py       # Subscription manager
```

## Refactoring Priority

### Phase 1: Split routes.py (Highest Impact)
1. Create api/health.py with all health check endpoints
2. Create api/proxy/ directory with service-specific files
3. Create system/ directory for container and stats endpoints
4. Update main.py to include new routers

### Phase 2: Split auth_routes.py
1. Extract trust request handling to api/auth/trust.py
2. Extract admin endpoints to api/auth/admin.py
3. Keep core auth flows in api/auth/routes.py

### Phase 3: Reorganize user_profiles.py
1. Extract models and constants to profiles/models.py
2. Extract DB operations to profiles/db.py
3. Extract permission logic to profiles/permissions.py

### Phase 4: Test Updates
- Move tests to match new structure
- Update imports in all test files
- Ensure coverage remains at 80%+

## Migration Strategy

1. Create new files with extracted code
2. Add deprecation re-exports in old files
3. Update imports one file at a time
4. Run tests after each change
5. Remove old files when all imports updated

## Risk Assessment

| Risk | Mitigation |
|------|------------|
| Breaking imports | Add re-exports for backward compatibility |
| Test failures | Run tests after each file split |
| CI failures | Make incremental commits, monitor CI |
| Runtime errors | Keep functions together that share state |

## Not Refactoring (Acceptable as-is)

- `controllers/ac_controller.py` (601 lines): Cohesive, single responsibility
- `controllers/state_machine.py` (343 lines): Pure logic, well-structured
- `auth_users.py` (303 lines): Cohesive user management
- `main.py` (268 lines): FastAPI app setup, acceptable size

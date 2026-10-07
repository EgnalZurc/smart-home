"""User profiles and app permission system for Cuchi Casa.

DEPRECATION NOTICE:
This module has been refactored into the `profiles` package.
All imports are re-exported here for backwards compatibility.

Please update imports to use:
    from profiles import <function>
    # or
    from profiles.constants import APP_REGISTRY
    from profiles.db import get_all_profiles
    from profiles.permissions import get_effective_level

Profiles
--------
Each profile has an immutable ID (UUID) that is used for all references.
The name and description are editable (except for SUPER which is fully protected).

Profile attributes:
- ``id``          : UUID, immutable, primary key
- ``name``        : display name, editable
- ``level``       : permission level (0-3), editable
- ``description`` : description text, editable

Level semantics
---------------
Level 0 = SUPER — sees everything, configures everything, admin access
Level 1 = Full family access — sees all standard apps
Level 2 = Reserved for future use
Level 3 = Restricted — only specific apps (e.g., GAMER sees only Valheim)

Database
--------
Table ``profiles`` in auth.db:
    id          TEXT PRIMARY KEY (UUID)
    name        TEXT NOT NULL UNIQUE
    level       INTEGER NOT NULL
    description TEXT DEFAULT ''
    protected   INTEGER DEFAULT 0 (1 = cannot edit/delete)

Table ``user_profiles`` in auth.db:
    username   TEXT NOT NULL
    profile_id TEXT NOT NULL (references profiles.id)
    PRIMARY KEY (username, profile_id)
"""

# Re-export everything from the profiles package for backwards compatibility
from profiles import (
    _BUILTIN_NAME_TO_ID,
    APP_REGISTRY,
    AUTH_DB_PATH,
    BUILTIN_NAME_TO_ID,
    BUILTIN_PROFILES,
    DEFAULT_PROFILE_ID,
    EXTERNAL_SERVICES,
    _can_view,
    _ensure_builtin_profiles,
    add_user_profile,
    app_permissions,
    create_profile,
    delete_profile,
    get_all_profiles,
    get_effective_level,
    get_profile,
    get_profile_by_id,
    get_profile_by_name,
    get_profile_key,
    get_user_info,
    get_user_profiles,
    get_user_profiles_detailed,
    init_database,
    is_super,
    remove_user_profile,
    set_user_profiles,
    update_profile,
    visible_external_services,
)

__all__ = [
    # Constants
    "AUTH_DB_PATH",
    "APP_REGISTRY",
    "BUILTIN_PROFILES",
    "BUILTIN_NAME_TO_ID",
    "_BUILTIN_NAME_TO_ID",
    "DEFAULT_PROFILE_ID",
    "EXTERNAL_SERVICES",
    # DB operations
    "init_database",
    "get_all_profiles",
    "get_profile_by_id",
    "get_profile_by_name",
    "create_profile",
    "update_profile",
    "delete_profile",
    "get_user_profiles",
    "set_user_profiles",
    "add_user_profile",
    "remove_user_profile",
    "_ensure_builtin_profiles",
    # Permissions
    "get_effective_level",
    "is_super",
    "app_permissions",
    "visible_external_services",
    "get_user_profiles_detailed",
    "get_user_info",
    "get_profile_key",
    "get_profile",
    "_can_view",
]

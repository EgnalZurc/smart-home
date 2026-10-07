"""User profiles and app permission system for Cuchi Casa.

This package is organized into:
- constants: Profile definitions, app registry, external services
- db: Database operations (CRUD for profiles and user assignments)
- permissions: Permission logic and user info aggregation

For backwards compatibility, all public APIs are re-exported here.
"""

import logging

# Re-export constants
from .constants import (
    APP_REGISTRY,
    BUILTIN_NAME_TO_ID,
    BUILTIN_PROFILES,
    DEFAULT_PROFILE_ID,
    EXTERNAL_SERVICES,
)

# Re-export DB operations
from .db import (
    AUTH_DB_PATH,
    _ensure_builtin_profiles,
    add_user_profile,
    create_profile,
    delete_profile,
    get_all_profiles,
    get_profile_by_id,
    get_profile_by_name,
    get_user_profiles,
    init_database,
    remove_user_profile,
    set_user_profiles,
    update_profile,
)

# Re-export permission functions
from .permissions import (
    _can_view,
    app_permissions,
    get_effective_level,
    get_profile,
    get_profile_key,
    get_user_info,
    get_user_profiles_detailed,
    is_super,
    visible_external_services,
)

logger = logging.getLogger(__name__)

# Legacy alias for internal constant
_BUILTIN_NAME_TO_ID = BUILTIN_NAME_TO_ID

__all__ = [
    # Constants
    "AUTH_DB_PATH",
    "APP_REGISTRY",
    "BUILTIN_PROFILES",
    "BUILTIN_NAME_TO_ID",
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
    # Legacy
    "_BUILTIN_NAME_TO_ID",
]

# Run database initialization on module load
try:
    init_database()
except Exception as e:
    logger.warning("Profile initialization failed: %s", e)

"""Auth API subpackage.

Contains:
- admin.py: Admin endpoints for user/profile management (SUPER only)
"""

from .admin import router as admin_router

__all__ = ["admin_router"]

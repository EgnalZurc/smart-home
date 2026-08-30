"""One-time migration: create user_profiles table and assign initial profiles.

Run once on the Raspberry Pi after deploying user_profiles.py:

    docker exec smart-home-backend python /app/migrate_profiles.py

Assignments
-----------
- egnal  → SUPER
- virchi → FAMILIA_PRINCIPAL
"""
import os
import sys

# Allow running directly without the full app context by pointing to the real DB.
AUTH_DB_PATH = os.environ.get("AUTH_DB_PATH", "/app/data/auth.db")

# Inject path so user_profiles can find the DB.
import user_profiles
user_profiles.AUTH_DB_PATH = AUTH_DB_PATH

INITIAL_PROFILES = {
    "egnal":  "SUPER",
    "virchi": "FAMILIA_PRINCIPAL",
}

def main() -> None:
    print(f"Migration target: {AUTH_DB_PATH}")
    for username, profile_key in INITIAL_PROFILES.items():
        try:
            user_profiles.set_profile(username, profile_key)
            print(f"  ✓ {username} → {profile_key}")
        except Exception as exc:
            print(f"  ✗ {username}: {exc}", file=sys.stderr)
    print("Done.")

if __name__ == "__main__":
    main()

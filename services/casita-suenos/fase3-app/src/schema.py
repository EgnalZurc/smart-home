"""
Definiciones de esquema SQLite para Casita Sueños.

Este módulo contiene:
  - _SCHEMA: DDL para crear las tablas e índices
  - _DEFAULT_SCHEDULE: configuración de automatizaciones por defecto
  - _VALID_UID_PATTERN: patrón de validación para property UIDs
  - _validate_property_uid(): función de validación
"""

from __future__ import annotations

import re

# --------------------------------------------------------------------------
# SQL Injection Prevention
# --------------------------------------------------------------------------
# All user-facing data is passed via parameterized queries (?-placeholders).
# String interpolation (f-strings) is ONLY used for:
#   1. Column/table names from internal constants (schema, migrations)
#   2. Validated sort columns (resolved through _SORT_MAP whitelist)
#   3. Hardcoded filter clauses (e.g., "AND s.viewed = 1")
#
# property_uid values originate from scraper discovery (portal:portal_id format)
# and are validated before any SQL operation to prevent injection if the data
# source changes in the future.
# --------------------------------------------------------------------------

# Pattern for valid property UIDs: portal:id where both are alphanumeric/underscore
# Examples: "pisos:12345", "idealista:abc_123", "habitaclia:prop-456"
_VALID_UID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+:[a-zA-Z0-9_-]+$")


def _validate_property_uid(uid: str) -> None:
    """Validate that a property UID matches the expected format.

    UIDs come from portal discovery (portal:portal_id) and should only contain
    alphanumeric characters, underscores, and hyphens. This validation prevents
    SQL injection if the data source changes or is compromised.

    Raises:
        ValueError: If the UID contains unexpected characters.
    """
    if not uid or not _VALID_UID_PATTERN.match(uid):
        raise ValueError(
            f"Invalid property_uid format: {uid!r}. "
            "Expected 'portal:id' with alphanumeric/underscore/hyphen characters."
        )


_SCHEMA = """
CREATE TABLE IF NOT EXISTS properties (
    uid             TEXT PRIMARY KEY,
    portal          TEXT NOT NULL,
    portal_id       TEXT NOT NULL,
    zone_id         TEXT NOT NULL,
    url             TEXT NOT NULL,
    title           TEXT NOT NULL,
    price           INTEGER NOT NULL,
    rooms           INTEGER,
    size_m2         REAL,
    has_garage      INTEGER NOT NULL DEFAULT 0,
    has_garden      INTEGER NOT NULL DEFAULT 0,
    piscina         TEXT NOT NULL DEFAULT 'ninguna',
    habitable       INTEGER NOT NULL DEFAULT 1,
    has_ac          INTEGER NOT NULL DEFAULT 0,
    description     TEXT NOT NULL DEFAULT '',
    first_seen      TEXT NOT NULL,
    last_seen       TEXT NOT NULL,
    source          TEXT NOT NULL DEFAULT '',
    published_at    TEXT
);

CREATE TABLE IF NOT EXISTS price_history (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    property_uid    TEXT NOT NULL,
    old_price       INTEGER NOT NULL,
    new_price       INTEGER NOT NULL,
    delta_pct       REAL NOT NULL,
    detected_at     TEXT NOT NULL,
    FOREIGN KEY (property_uid) REFERENCES properties(uid)
);

CREATE TABLE IF NOT EXISTS scored_properties (
    property_uid    TEXT PRIMARY KEY,
    zone_id         TEXT NOT NULL,
    score_total     REAL NOT NULL,
    score_p1        REAL NOT NULL,
    score_p2        REAL NOT NULL,
    score_p3        REAL NOT NULL,
    score_p4        REAL NOT NULL,
    score_p5        REAL NOT NULL,
    score_p6        REAL NOT NULL,
    score_p7        REAL NOT NULL,
    score_p8        REAL NOT NULL,
    score_p9        REAL NOT NULL,
    score_p10       REAL NOT NULL,
    score_p11       REAL NOT NULL DEFAULT 0,
    score_p12       REAL NOT NULL DEFAULT 0,
    score_p13       REAL NOT NULL DEFAULT 0,
    scored_at       TEXT NOT NULL,
    alerted         INTEGER NOT NULL DEFAULT 0,
    dismissed       INTEGER NOT NULL DEFAULT 0,
    dismissed_at    TEXT,
    viewed          INTEGER NOT NULL DEFAULT 0,
    viewed_at       TEXT,
    comment         TEXT NOT NULL DEFAULT '',
    FOREIGN KEY (property_uid) REFERENCES properties(uid)
);

CREATE TABLE IF NOT EXISTS schedule_config (
    key             TEXT PRIMARY KEY,
    value           TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS weekly_summaries (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    sent_at         TEXT NOT NULL,
    content         TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_properties_zone ON properties(zone_id);
CREATE INDEX IF NOT EXISTS idx_properties_price ON properties(price);
CREATE INDEX IF NOT EXISTS idx_properties_first_seen ON properties(first_seen DESC);
CREATE INDEX IF NOT EXISTS idx_scored_total ON scored_properties(score_total DESC);
CREATE INDEX IF NOT EXISTS idx_scored_dismissed ON scored_properties(dismissed);
CREATE INDEX IF NOT EXISTS idx_price_history_uid ON price_history(property_uid);
CREATE TABLE IF NOT EXISTS telegram_chats (
    chat_id     TEXT PRIMARY KEY,
    username    TEXT NOT NULL DEFAULT '',
    registered_at TEXT NOT NULL
);
"""

# Configuración de schedule por defecto
_DEFAULT_SCHEDULE = {
    "scraping_enabled": True,
    "scraping_days": [0, 3],  # lunes=0, jueves=3
    "scraping_hour": 7,
    "gmail_check_enabled": True,
    "gmail_interval_min": 30,
    "summary_enabled": True,
    "summary_day": 6,  # domingo
    "summary_hour": 9,
}

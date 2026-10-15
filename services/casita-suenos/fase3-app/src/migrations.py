"""
Migraciones de esquema SQLite para Casita Sueños.

Este módulo contiene la lógica de migraciones no destructivas
para añadir columnas nuevas a tablas existentes.
"""

from __future__ import annotations

import contextlib
import logging
import sqlite3

logger = logging.getLogger(__name__)


def run_migrations(conn: sqlite3.Connection) -> None:
    """Ejecuta migraciones no destructivas para añadir columnas nuevas a tablas existentes.

    Args:
        conn: Conexión SQLite abierta con la base de datos.
    """
    # Migraciones de scored_properties (p11-p13, dismissed, viewed, comment)
    migrations = [
        ("scored_properties", "score_p11", "REAL NOT NULL DEFAULT 0"),
        ("scored_properties", "score_p12", "REAL NOT NULL DEFAULT 0"),
        ("scored_properties", "score_p13", "REAL NOT NULL DEFAULT 0"),
        ("scored_properties", "dismissed", "INTEGER NOT NULL DEFAULT 0"),
        ("scored_properties", "dismissed_at", "TEXT"),
        ("scored_properties", "viewed", "INTEGER NOT NULL DEFAULT 0"),
        ("scored_properties", "viewed_at", "TEXT"),
        ("scored_properties", "comment", "TEXT NOT NULL DEFAULT ''"),
    ]
    for table, col, definition in migrations:
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {definition}")
            logger.info("[db] Migración: añadida columna %s.%s", table, col)
        except sqlite3.OperationalError:
            pass  # columna ya existe

    # Migración: published_at en properties
    try:
        conn.execute("ALTER TABLE properties ADD COLUMN published_at TEXT")
        logger.info("[db] Migración: añadida columna properties.published_at")
    except sqlite3.OperationalError:
        pass  # ya existe

    # Migración: has_ac en properties
    try:
        conn.execute(
            "ALTER TABLE properties ADD COLUMN has_ac INTEGER NOT NULL DEFAULT 0"
        )
        logger.info("[db] Migración: has_ac en properties")
    except sqlite3.OperationalError:
        pass  # ya existe

    # Rework R1-R18: nuevas columnas en properties
    new_cols_props = [
        ("properties", "terrain_m2", "REAL"),
        ("properties", "garage_type", "TEXT NOT NULL DEFAULT 'ninguno'"),
        ("properties", "habitability", "TEXT NOT NULL DEFAULT 'desconocido'"),
        ("properties", "internet", "TEXT NOT NULL DEFAULT 'ninguno'"),
        ("properties", "has_ac_preinstalled", "INTEGER NOT NULL DEFAULT 0"),
    ]
    for table, col, defn in new_cols_props:
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {defn}")
            logger.info("[db] Migración R1-R18: añadida %s.%s", table, col)
        except sqlite3.OperationalError:
            pass  # ya existe

    # Rework: nuevas columnas en scored_properties (r8-r18)
    new_cols_score = [
        ("scored_properties", "score_r1", "REAL NOT NULL DEFAULT 0"),
        ("scored_properties", "score_r2", "REAL NOT NULL DEFAULT 0"),
        ("scored_properties", "score_r3", "REAL NOT NULL DEFAULT 0"),
        ("scored_properties", "score_r4", "REAL NOT NULL DEFAULT 0"),
        ("scored_properties", "score_r5", "REAL NOT NULL DEFAULT 0"),
        ("scored_properties", "score_r6", "REAL NOT NULL DEFAULT 0"),
        ("scored_properties", "score_r7", "REAL NOT NULL DEFAULT 0"),
        ("scored_properties", "score_r8", "REAL NOT NULL DEFAULT 0"),
        ("scored_properties", "score_r9", "REAL NOT NULL DEFAULT 0"),
        ("scored_properties", "score_r10", "REAL NOT NULL DEFAULT 0"),
        ("scored_properties", "score_r11", "REAL NOT NULL DEFAULT 0"),
        ("scored_properties", "score_r12", "REAL NOT NULL DEFAULT 0"),
        ("scored_properties", "score_r13", "REAL NOT NULL DEFAULT 0"),
        ("scored_properties", "score_r14", "REAL NOT NULL DEFAULT 0"),
        ("scored_properties", "score_r15", "REAL NOT NULL DEFAULT 0"),
        ("scored_properties", "score_r16", "REAL NOT NULL DEFAULT 0"),
        ("scored_properties", "score_r17", "REAL NOT NULL DEFAULT 0"),
        ("scored_properties", "score_r18", "REAL NOT NULL DEFAULT 0"),
    ]
    for table, col, defn in new_cols_score:
        try:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {defn}")
            logger.info("[db] Migración R1-R18: añadida %s.%s", table, col)
        except sqlite3.OperationalError:
            pass  # ya existe

    # Asegurar que tabla telegram_chats existe (por si la BD era antigua)
    with contextlib.suppress(Exception):
        conn.execute(
            "CREATE TABLE IF NOT EXISTS telegram_chats "
            "(chat_id TEXT PRIMARY KEY, username TEXT NOT NULL DEFAULT '', "
            "registered_at TEXT NOT NULL)"
        )

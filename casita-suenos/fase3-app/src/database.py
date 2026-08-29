"""
Capa de persistencia SQLite para Casita Sueños.

Tablas:
  - properties: anuncios vistos, con último precio conocido
  - price_history: historial de precios por anuncio
  - scored_properties: puntuaciones calculadas + dismissed + p11
  - schedule_config: configuración de automatizaciones (JSON)
  - weekly_summaries: histórico de resúmenes semanales enviados

Patrón del proyecto: sin ORM, SQL directo con sqlite3.
Siguiendo state_persistence.py del backend existente: fichero en /app/data/.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime
from pathlib import Path

from models import PriceEvent, Property, ScoredProperty

logger = logging.getLogger(__name__)

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
    "scraping_days": [0, 3],       # lunes=0, jueves=3
    "scraping_hour": 7,
    "gmail_check_enabled": True,
    "gmail_interval_min": 30,
    "summary_enabled": True,
    "summary_day": 6,              # domingo
    "summary_hour": 9,
}


class Database:
    """Gestiona la base de datos SQLite de Casita Sueños."""

    def __init__(self, db_path: str) -> None:
        self._path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._migrate()
        self._conn.commit()
        logger.info("[db] Base de datos inicializada en %s", db_path)

    def _migrate(self) -> None:
        """Migraciones no destructivas para añadir columnas nuevas a tablas existentes."""
        migrations = [
            ("scored_properties", "score_p11",    "REAL NOT NULL DEFAULT 0"),
            ("scored_properties", "score_p12",    "REAL NOT NULL DEFAULT 0"),
            ("scored_properties", "score_p13",    "REAL NOT NULL DEFAULT 0"),
            ("scored_properties", "dismissed",     "INTEGER NOT NULL DEFAULT 0"),
            ("scored_properties", "dismissed_at",  "TEXT"),
            ("scored_properties", "viewed",        "INTEGER NOT NULL DEFAULT 0"),
            ("scored_properties", "viewed_at",     "TEXT"),
            ("scored_properties", "comment",       "TEXT NOT NULL DEFAULT ''"),
        ]
        for table, col, definition in migrations:
            try:
                self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {definition}")
                logger.info("[db] Migración: añadida columna %s.%s", table, col)
            except sqlite3.OperationalError:
                pass  # columna ya existe
        # Migraci?n: published_at en properties
        try:
            self._conn.execute("ALTER TABLE properties ADD COLUMN published_at TEXT")
            logger.info("[db] Migracion: anadida columna properties.published_at")
        except sqlite3.OperationalError:
            pass  # ya existe
        # Migracion: has_ac en properties
        try:
            self._conn.execute("ALTER TABLE properties ADD COLUMN has_ac INTEGER NOT NULL DEFAULT 0")
            logger.info("[db] Migracion: has_ac en properties")
        except sqlite3.OperationalError:
            pass  # ya existe
        # Asegurar que tabla telegram_chats existe (por si la BD era antigua)
        try:
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS telegram_chats "
                "(chat_id TEXT PRIMARY KEY, username TEXT NOT NULL DEFAULT '', "
                "registered_at TEXT NOT NULL)"
            )
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Propiedades
    # ------------------------------------------------------------------

    def upsert_property(self, prop: Property) -> PriceEvent | None:
        uid = prop.unique_id
        now = datetime.now().isoformat()
        existing = self._conn.execute(
            "SELECT price FROM properties WHERE uid = ?", (uid,)
        ).fetchone()

        price_event: PriceEvent | None = None

        if existing:
            old_price = existing["price"]
            if old_price != prop.price:
                price_event = PriceEvent(
                    property_uid=uid,
                    old_price=old_price,
                    new_price=prop.price,
                    detected_at=datetime.now(),
                )
                logger.info(
                    "[db] Cambio de precio en %s: %d€ → %d€ (%.1f%%)",
                    uid, old_price, prop.price, price_event.delta_pct,
                )
                self._conn.execute(
                    "INSERT INTO price_history "
                    "(property_uid, old_price, new_price, delta_pct, detected_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (uid, old_price, prop.price, price_event.delta_pct, now),
                )
            self._conn.execute(
                "UPDATE properties SET price=?, last_seen=?, title=?, description=? "
                "WHERE uid=?",
                (prop.price, now, prop.title, prop.description, uid),
            )
        else:
            self._conn.execute(
                """INSERT INTO properties
                   (uid, portal, portal_id, zone_id, url, title, price, rooms, size_m2,
                    has_garage, has_garden, has_ac, piscina, habitable, description,
                    first_seen, last_seen, source, published_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    uid, prop.portal.value, prop.portal_id, prop.zone_id,
                    prop.url, prop.title, prop.price,
                    prop.rooms, prop.size_m2,
                    int(prop.has_garage), int(prop.has_garden_or_plot),
                    int(getattr(prop, 'has_ac', False)),
                    prop.piscina.value, int(prop.habitable),
                    prop.description,
                    prop.first_seen.isoformat(), now, prop.source,
                    getattr(prop, "published_at", None),
                ),
            )
            logger.debug("[db] Nueva propiedad: %s — %d€", uid, prop.price)

        self._conn.commit()
        return price_event

    def is_new(self, prop: Property) -> bool:
        row = self._conn.execute(
            "SELECT 1 FROM properties WHERE uid = ?", (prop.unique_id,)
        ).fetchone()
        return row is None

    # ------------------------------------------------------------------
    # Puntuaciones
    # ------------------------------------------------------------------

    def upsert_score(self, scored: ScoredProperty) -> None:
        uid = scored.prop.unique_id
        s = scored.score
        now = scored.scored_at.isoformat()

        existing = self._conn.execute(
            "SELECT alerted, dismissed, dismissed_at FROM scored_properties WHERE property_uid = ?",
            (uid,),
        ).fetchone()

        alerted    = existing["alerted"]     if existing else 0
        dismissed  = existing["dismissed"]   if existing else 0
        dism_at    = existing["dismissed_at"] if existing else None

        self._conn.execute(
            """INSERT OR REPLACE INTO scored_properties
               (property_uid, zone_id, score_total,
                score_p1, score_p2, score_p3, score_p4, score_p5,
                score_p6, score_p7, score_p8, score_p9, score_p10, score_p11, score_p12, score_p13,
                scored_at, alerted, dismissed, dismissed_at, viewed, viewed_at, comment)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                uid, scored.zone.id, s.total,
                s.p1_rooms, s.p2_piscina, s.p3_distance, s.p4_beach, s.p5_pools,
                s.p6_supermarket, s.p7_health, s.p8_hospital, s.p9_price,
                s.p10_fire, getattr(s, "p11_preference", 0.0), getattr(s, "p12_flood", 0.0), getattr(s, "p13_ac", 0.0),
                now, alerted, dismissed, dism_at, viewed, viewed_at, comment,
            ),
        )
        self._conn.commit()

    def mark_alerted(self, property_uid: str) -> None:
        self._conn.execute(
            """INSERT OR IGNORE INTO scored_properties
               (property_uid, zone_id, score_total,
                score_p1, score_p2, score_p3, score_p4, score_p5,
                score_p6, score_p7, score_p8, score_p9, score_p10, score_p11,
                scored_at, alerted)
               VALUES (?, '', 0, 0,0,0,0,0,0,0,0,0,0,0, ?, 0)""",
            (property_uid, datetime.now().isoformat()),
        )
        self._conn.execute(
            "UPDATE scored_properties SET alerted = 1 WHERE property_uid = ?",
            (property_uid,),
        )
        self._conn.commit()

    def is_alerted(self, property_uid: str) -> bool:
        row = self._conn.execute(
            "SELECT alerted FROM scored_properties WHERE property_uid = ?",
            (property_uid,),
        ).fetchone()
        return bool(row and row["alerted"])

    # ------------------------------------------------------------------
    # Descarte de propiedades
    # ------------------------------------------------------------------

    def dismiss(self, property_uid: str) -> bool:
        """Descarta una propiedad. Devuelve True si existía."""
        row = self._conn.execute(
            "SELECT 1 FROM scored_properties WHERE property_uid = ?",
            (property_uid,),
        ).fetchone()
        if not row:
            return False
        self._conn.execute(
            "UPDATE scored_properties SET dismissed=1, dismissed_at=? WHERE property_uid=?",
            (datetime.now().isoformat(), property_uid),
        )
        self._conn.commit()
        logger.info("[db] Propiedad descartada: %s", property_uid)
        return True

    def undismiss(self, property_uid: str) -> bool:
        """Recupera una propiedad descartada. Devuelve True si existía."""
        row = self._conn.execute(
            "SELECT 1 FROM scored_properties WHERE property_uid = ?",
            (property_uid,),
        ).fetchone()
        if not row:
            return False
        self._conn.execute(
            "UPDATE scored_properties SET dismissed=0, dismissed_at=NULL WHERE property_uid=?",
            (property_uid,),
        )
        self._conn.commit()
        logger.info("[db] Propiedad recuperada: %s", property_uid)
        return True

    def get_dismissed(self) -> list[dict]:
        """Devuelve propiedades descartadas, ordenadas por fecha de descarte."""
        rows = self._conn.execute(
            """SELECT p.uid, p.title, p.price, p.url, p.zone_id, p.rooms, p.size_m2,
                      s.score_total, s.dismissed_at
               FROM scored_properties s
               JOIN properties p ON p.uid = s.property_uid
               WHERE s.dismissed = 1
               ORDER BY s.dismissed_at DESC""",
        ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Radar de casas (para la UI)
    # ------------------------------------------------------------------

    def get_radar_properties(
        self,
        min_score: float = 55.0,
        limit: int = 20,
        offset: int = 0,
        sort_by: str = "score",   # score | price | distance | portal | zone
        sort_dir: str = "desc",
    ) -> dict:
        """
        Devuelve propiedades en el radar con paginación y ordenación configurable.
        Retorna: {items: [...], total: int, has_more: bool}
        """
        _SORT_MAP = {
            "score":    "s.score_total",
            "price":    "p.price",
            "distance": "p.first_seen",  # distancia no está en BD, fallback a fecha
            "portal":   "p.portal",
            "zone":     "p.zone_id",
            "date":     "p.first_seen",
        }
        order_col = _SORT_MAP.get(sort_by, "s.score_total")
        order_dir = "DESC" if sort_dir.lower() == "desc" else "ASC"

        total = self._conn.execute(
            "SELECT COUNT(*) FROM scored_properties s "
            "JOIN properties p ON p.uid=s.property_uid "
            "WHERE s.score_total >= ? AND s.dismissed = 0",
            (min_score,),
        ).fetchone()[0]

        rows = self._conn.execute(
            f"""SELECT p.uid, p.title, p.price, p.url, p.zone_id,
                      p.portal, p.portal_id,
                      p.rooms, p.size_m2, p.piscina, p.has_garage,
                      p.first_seen, p.last_seen, p.published_at,
                      s.score_total, s.score_p1, s.score_p2, s.score_p3,
                      s.score_p4, s.score_p5, s.score_p6, s.score_p7,
                      s.score_p8, s.score_p9, s.score_p10, s.score_p11,
                      COALESCE(s.score_p12, 0) as score_p12,
                      COALESCE(s.viewed, 0) as viewed,
                      s.viewed_at, COALESCE(s.comment, '') as comment
               FROM scored_properties s
               JOIN properties p ON p.uid = s.property_uid
               WHERE s.score_total >= ? AND s.dismissed = 0
               ORDER BY {order_col} {order_dir}
               LIMIT ? OFFSET ?""",
            (min_score, limit, offset),
        ).fetchall()

        items = [dict(r) for r in rows]
        return {
            "items": items,
            "total": total,
            "offset": offset,
            "limit": limit,
            "has_more": (offset + limit) < total,
        }

    # ------------------------------------------------------------------
    # Resumen semanal
    # ------------------------------------------------------------------

    def save_weekly_summary(self, content: str) -> None:
        """Guarda el contenido del último resumen semanal enviado."""
        now = datetime.now().isoformat()
        self._conn.execute(
            "INSERT INTO weekly_summaries (sent_at, content) VALUES (?, ?)",
            (now, content),
        )
        self._conn.commit()

    def get_last_weekly_summary(self) -> dict | None:
        """Devuelve el último resumen semanal guardado."""
        row = self._conn.execute(
            "SELECT sent_at, content FROM weekly_summaries ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None

    # ------------------------------------------------------------------
    # Configuración de automatizaciones
    # ------------------------------------------------------------------

    def get_schedule_config(self) -> dict:
        """Devuelve la configuración de schedule (con defaults si no existe)."""
        rows = self._conn.execute("SELECT key, value FROM schedule_config").fetchall()
        config = dict(_DEFAULT_SCHEDULE)
        for row in rows:
            try:
                config[row["key"]] = json.loads(row["value"])
            except Exception:
                config[row["key"]] = row["value"]
        return config

    def save_schedule_config(self, config: dict) -> None:
        """Guarda la configuración de schedule."""
        for key, value in config.items():
            self._conn.execute(
                "INSERT OR REPLACE INTO schedule_config (key, value) VALUES (?, ?)",
                (key, json.dumps(value)),
            )
        self._conn.commit()

    # ------------------------------------------------------------------
    # Consultas generales
    # ------------------------------------------------------------------

    def get_top_scored(self, limit: int = 10, min_score: float = 50.0) -> list[dict]:
        """Devuelve las N propiedades con mayor puntuación, excluidas las descartadas."""
        rows = self._conn.execute(
            """SELECT p.*, s.score_total, s.zone_id as score_zone
               FROM scored_properties s
               JOIN properties p ON p.uid = s.property_uid
               WHERE s.score_total >= ? AND s.dismissed = 0
               ORDER BY s.score_total DESC
               LIMIT ?""",
            (min_score, limit),
        ).fetchall()
        return [dict(r) for r in rows]

    def get_recent_price_drops(self, limit: int = 10) -> list[dict]:
        rows = self._conn.execute(
            """SELECT ph.*, p.title, p.url, p.zone_id
               FROM price_history ph
               JOIN properties p ON p.uid = ph.property_uid
               ORDER BY ph.detected_at DESC, ph.delta_pct ASC
               LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def count_properties(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM properties").fetchone()[0]

    def count_by_zone(self) -> dict[str, int]:
        rows = self._conn.execute(
            "SELECT zone_id, COUNT(*) as cnt FROM properties GROUP BY zone_id"
        ).fetchall()
        return {r["zone_id"]: r["cnt"] for r in rows}

    # ------------------------------------------------------------------
    # Visto y comentarios
    # ------------------------------------------------------------------
    def mark_viewed(self, property_uid: str) -> bool:
        """Marca una propiedad como vista. Devuelve True si existia."""
        row = self._conn.execute(
            "SELECT 1 FROM scored_properties WHERE property_uid = ?", (property_uid,)
        ).fetchone()
        if not row:
            return False
        now = datetime.now().isoformat()
        self._conn.execute(
            "UPDATE scored_properties SET viewed=1, viewed_at=? WHERE property_uid=?",
            (now, property_uid),
        )
        self._conn.commit()
        return True

    def save_comment(self, property_uid: str, comment: str) -> bool:
        """Guarda un comentario para una propiedad. Devuelve True si existia."""
        row = self._conn.execute(
            "SELECT 1 FROM scored_properties WHERE property_uid = ?", (property_uid,)
        ).fetchone()
        if not row:
            return False
        self._conn.execute(
            "UPDATE scored_properties SET comment=? WHERE property_uid=?",
            (comment.strip(), property_uid),
        )
        self._conn.commit()
        return True

    # ------------------------------------------------------------------
    # Telegram chats
    # ------------------------------------------------------------------
    def register_telegram_chat(self, chat_id: str, username: str = "") -> None:
        """Registra o actualiza un chat_id de Telegram."""
        now = datetime.now().isoformat()
        self._conn.execute(
            "INSERT OR REPLACE INTO telegram_chats "
            "(chat_id, username, registered_at) VALUES (?, ?, ?)",
            (str(chat_id), username or "", now),
        )
        self._conn.commit()
        logger.info("[db] Telegram chat registrado: %s (%s)", chat_id, username)

    def get_telegram_chat_ids(self) -> list[str]:
        """Devuelve todos los chat_ids registrados."""
        rows = self._conn.execute(
            "SELECT chat_id FROM telegram_chats ORDER BY registered_at"
        ).fetchall()
        return [r["chat_id"] for r in rows]

    def close(self) -> None:
        self._conn.close()
        logger.info("[db] Conexión cerrada")

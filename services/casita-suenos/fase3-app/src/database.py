"""
Capa de persistencia SQLite para Casita Sue├▒os.

Tablas:
  - properties: anuncios vistos, con ├║ltimo precio conocido
  - price_history: historial de precios por anuncio
  - scored_properties: puntuaciones calculadas + dismissed + p11
  - schedule_config: configuraci├│n de automatizaciones (JSON)
  - weekly_summaries: hist├│rico de res├║menes semanales enviados

Patr├│n del proyecto: sin ORM, SQL directo con sqlite3.
Siguiendo state_persistence.py del backend existente: fichero en /app/data/.
"""

from __future__ import annotations

import contextlib
import json
import logging
import sqlite3
from datetime import datetime, timedelta
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

# Configuraci├│n de schedule por defecto
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


class Database:
    """Gestiona la base de datos SQLite de Casita Sue├▒os."""

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
        """Migraciones no destructivas para a├▒adir columnas nuevas a tablas existentes."""
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
                self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {definition}")
                logger.info("[db] Migraci├│n: a├▒adida columna %s.%s", table, col)
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
            self._conn.execute(
                "ALTER TABLE properties ADD COLUMN has_ac INTEGER NOT NULL DEFAULT 0"
            )
            logger.info("[db] Migracion: has_ac en properties")
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
                self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {defn}")
                logger.info("[db] Migraci├│n R1-R18: a├▒adida %s.%s", table, col)
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
                self._conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {defn}")
                logger.info("[db] Migraci├│n R1-R18: a├▒adida %s.%s", table, col)
            except sqlite3.OperationalError:
                pass  # ya existe
        # Asegurar que tabla telegram_chats existe (por si la BD era antigua)
        with contextlib.suppress(Exception):
            self._conn.execute(
                "CREATE TABLE IF NOT EXISTS telegram_chats "
                "(chat_id TEXT PRIMARY KEY, username TEXT NOT NULL DEFAULT '', "
                "registered_at TEXT NOT NULL)"
            )

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
                    "[db] Cambio de precio en %s: %dÔé¼ ÔåÆ %dÔé¼ (%.1f%%)",
                    uid,
                    old_price,
                    prop.price,
                    price_event.delta_pct,
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
                    first_seen, last_seen, source, published_at,
                    terrain_m2, garage_type, habitability, internet, has_ac_preinstalled)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    uid,
                    prop.portal.value,
                    prop.portal_id,
                    prop.zone_id,
                    prop.url,
                    prop.title,
                    prop.price,
                    prop.rooms,
                    prop.size_m2,
                    int(prop.has_garage),
                    int(prop.has_garden_or_plot),
                    int(getattr(prop, "has_ac", False)),
                    prop.piscina.value,
                    int(prop.habitable),
                    prop.description,
                    prop.first_seen.isoformat(),
                    now,
                    prop.source,
                    getattr(prop, "published_at", None),
                    getattr(prop, "terrain_m2", None),
                    getattr(prop, "garage_type", "ninguno").value
                    if hasattr(getattr(prop, "garage_type", None), "value")
                    else str(getattr(prop, "garage_type", "ninguno")),
                    getattr(prop, "habitability", "desconocido").value
                    if hasattr(getattr(prop, "habitability", None), "value")
                    else str(getattr(prop, "habitability", "desconocido")),
                    getattr(prop, "internet", "ninguno").value
                    if hasattr(getattr(prop, "internet", None), "value")
                    else str(getattr(prop, "internet", "ninguno")),
                    int(getattr(prop, "has_ac_preinstalled", False)),
                ),
            )
            logger.debug("[db] Nueva propiedad: %s ÔÇö %dÔé¼", uid, prop.price)

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
            "SELECT alerted, dismissed, dismissed_at, COALESCE(viewed,0) as viewed, viewed_at, COALESCE(comment,'') as comment FROM scored_properties WHERE property_uid = ?",
            (uid,),
        ).fetchone()

        alerted = existing["alerted"] if existing else 0
        dismissed = existing["dismissed"] if existing else 0
        dism_at = existing["dismissed_at"] if existing else None
        viewed = existing["viewed"] if existing else 0
        viewed_at = existing["viewed_at"] if existing else None
        comment = existing["comment"] if existing else ""

        self._conn.execute(
            """INSERT OR REPLACE INTO scored_properties
               (property_uid, zone_id, score_total,
                score_p1, score_p2, score_p3, score_p4, score_p5,
                score_p6, score_p7, score_p8, score_p9, score_p10, score_p11, score_p12, score_p13,
                score_r1, score_r2, score_r3, score_r4, score_r5, score_r6,
                score_r7, score_r8, score_r9, score_r10, score_r11, score_r12,
                score_r13, score_r14, score_r15, score_r16, score_r17, score_r18,
                scored_at, alerted, dismissed, dismissed_at, viewed, viewed_at, comment)
               VALUES (?, ?, ?,
                       ?, ?, ?, ?, ?,
                       ?, ?, ?, ?, ?, ?, ?, ?,
                       ?, ?, ?, ?, ?, ?,
                       ?, ?, ?, ?, ?, ?,
                       ?, ?, ?, ?, ?, ?,
                       ?, ?, ?, ?, ?, ?, ?)""",
            (
                uid,
                scored.zone.id,
                s.total,
                # legado p1-p13 (0 si nuevo sistema)
                getattr(s, "p1_rooms", getattr(s, "r1_rooms", 0.0)),
                getattr(s, "p2_piscina", getattr(s, "r5_piscina", 0.0)),
                getattr(s, "p3_distance", getattr(s, "r12_madrid", 0.0)),
                getattr(s, "p4_beach", getattr(s, "r13_beach", 0.0)),
                getattr(s, "p5_pools", getattr(s, "r14_pools", 0.0)),
                getattr(s, "p6_supermarket", getattr(s, "r8_supermarket", 0.0)),
                getattr(s, "p7_health", getattr(s, "r9_health", 0.0)),
                getattr(s, "p8_hospital", getattr(s, "r10_hospital", 0.0)),
                getattr(s, "p9_price", getattr(s, "r7_price", 0.0)),
                getattr(s, "p10_fire", getattr(s, "r15_fire", 0.0)),
                getattr(s, "p11_preference", 0.0),
                getattr(s, "p12_flood", getattr(s, "r16_flood", 0.0)),
                getattr(s, "p13_ac", getattr(s, "r6_ac", 0.0)),
                # R1-R18
                getattr(s, "r1_rooms", 0.0),
                getattr(s, "r2_terrain", 0.0),
                getattr(s, "r3_garage", 0.0),
                getattr(s, "r4_habitability", 0.0),
                getattr(s, "r5_piscina", 0.0),
                getattr(s, "r6_ac", 0.0),
                getattr(s, "r7_price", 0.0),
                getattr(s, "r8_supermarket", 0.0),
                getattr(s, "r9_health", 0.0),
                getattr(s, "r10_hospital", 0.0),
                getattr(s, "r11_internet", 0.0),
                getattr(s, "r12_madrid", 0.0),
                getattr(s, "r13_beach", 0.0),
                getattr(s, "r14_pools", 0.0),
                getattr(s, "r15_fire", 0.0),
                getattr(s, "r16_flood", 0.0),
                getattr(s, "r17_coast", 0.0),
                getattr(s, "r18_beach_plot", 0.0),
                now,
                alerted,
                dismissed,
                dism_at,
                viewed,
                viewed_at,
                comment,
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
        """Descarta una propiedad. Devuelve True si exist├¡a."""
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
        """Recupera una propiedad descartada. Devuelve True si exist├¡a."""
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
        """Devuelve propiedades descartadas: vistas primero, luego por fecha."""
        rows = self._conn.execute(
            """SELECT p.uid, p.title, p.price, p.url, p.zone_id, p.rooms, p.size_m2,
                      s.score_total, s.dismissed_at,
                      COALESCE(s.viewed, 0) as viewed,
                      s.viewed_at, COALESCE(s.comment, '') as comment
               FROM scored_properties s
               JOIN properties p ON p.uid = s.property_uid
               WHERE s.dismissed = 1
               ORDER BY s.viewed DESC, s.dismissed_at DESC""",
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
        sort_by: str = "score",  # score | price | distance | portal | zone
        sort_dir: str = "desc",
        filter_by: str | None = None,  # viewed | not_viewed | None
        portal_filter: str | None = None,  # pisos | habitaclia | idealista | None
    ) -> dict:
        """
        Devuelve propiedades en el radar con paginaci├│n y ordenaci├│n configurable.
        Retorna: {items: [...], total: int, has_more: bool}
        """
        _SORT_MAP = {
            "score": "s.score_total",
            "price": "p.price",
            "distance": "p.first_seen",  # distancia no est├í en BD, fallback a fecha
            "portal": "p.portal",
            "zone": "p.zone_id",
            "date": "p.first_seen",
        }
        # SQL-injection safe: sort_by is resolved through the _SORT_MAP
        # whitelist (unknown keys fall back to s.score_total), and sort_dir
        # collapses to one of two hardcoded literals. User input never reaches
        # the interpolated f-string below; only trusted constants do.
        order_col = _SORT_MAP.get(sort_by, "s.score_total")
        order_dir = "DESC" if sort_dir.lower() == "desc" else "ASC"

        _fc = (
            "AND s.viewed = 1"
            if filter_by == "viewed"
            else ("AND COALESCE(s.viewed,0) = 0" if filter_by == "not_viewed" else "")
        )
        # Validate portal_filter against whitelist to prevent SQL injection
        VALID_PORTALS = {"pisos", "habitaclia", "idealista", "fotocasa"}
        _pf = ""
        params = [min_score]
        if portal_filter and portal_filter in VALID_PORTALS:
            _pf = "AND p.portal = ?"
            params.append(portal_filter)

        total = self._conn.execute(
            f"SELECT COUNT(*) FROM scored_properties s "  # nosec B608
            f"JOIN properties p ON p.uid=s.property_uid "
            f"WHERE s.score_total >= ? AND s.dismissed = 0 {_fc} {_pf}",
            params,
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
               WHERE s.score_total >= ? AND s.dismissed = 0 {_fc} {_pf}
               ORDER BY {order_col} {order_dir}
               LIMIT ? OFFSET ?""",  # nosec B608
            params + [limit, offset],
        ).fetchall()

        items = [dict(r) for r in rows]
        # Enriquecer cada item con el an├ílisis precio/m┬▓ vs media de la zona.
        # Se cachea la media por zona para no repetir la agregaci├│n por item.
        _zone_avg_cache: dict[str, float | None] = {}
        for item in items:
            zone_id = item.get("zone_id", "")
            size_m2 = item.get("size_m2")
            price = item.get("price")
            if size_m2 and size_m2 > 0 and price is not None:
                price_per_m2 = round(price / size_m2, 2)
            else:
                price_per_m2 = None
            if zone_id not in _zone_avg_cache:
                _zone_avg_cache[zone_id] = self.get_zone_avg_price_per_m2(zone_id)
            item.update(
                self._build_price_per_m2_dict(price_per_m2, _zone_avg_cache[zone_id])
            )
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
        """Guarda el contenido del ├║ltimo resumen semanal enviado."""
        now = datetime.now().isoformat()
        self._conn.execute(
            "INSERT INTO weekly_summaries (sent_at, content) VALUES (?, ?)",
            (now, content),
        )
        self._conn.commit()

    def get_last_weekly_summary(self) -> dict | None:
        """Devuelve el ├║ltimo resumen semanal guardado."""
        row = self._conn.execute(
            "SELECT sent_at, content FROM weekly_summaries ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None

    # ------------------------------------------------------------------
    # Configuraci├│n de automatizaciones
    # ------------------------------------------------------------------

    def get_schedule_config(self) -> dict:
        """Devuelve la configuraci├│n de schedule (con defaults si no existe)."""
        rows = self._conn.execute("SELECT key, value FROM schedule_config").fetchall()
        config = dict(_DEFAULT_SCHEDULE)
        for row in rows:
            try:
                config[row["key"]] = json.loads(row["value"])
            except Exception:
                config[row["key"]] = row["value"]
        return config

    def save_schedule_config(self, config: dict) -> None:
        """Guarda la configuraci├│n de schedule."""
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
        """Devuelve las N propiedades con mayor puntuaci├│n, excluidas las descartadas."""
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

    def get_recent_high_scorers(
        self,
        cutoff_iso: str,
        min_score: float,
        limit: int = 50,
    ) -> list[dict]:
        """Devuelve propiedades puntuadas por encima de ``min_score`` cuyo
        ``scored_at`` es posterior a ``cutoff_iso`` (ISO-8601), excluyendo las
        descartadas. Usado por el endpoint /api/casita/alerts del sistema de
        alertas unificado.

        Nota: ``scored_at`` se almacena como texto ISO-8601, por lo que la
        comparaci├│n lexicogr├ífica equivale a comparaci├│n cronol├│gica.
        """
        rows = self._conn.execute(
            """SELECT p.uid, p.title, p.price, p.url, p.zone_id,
                      s.score_total, s.scored_at
               FROM scored_properties s
               JOIN properties p ON p.uid = s.property_uid
               WHERE s.score_total >= ?
                 AND s.scored_at >= ?
                 AND s.dismissed = 0
               ORDER BY s.scored_at DESC
               LIMIT ?""",
            (min_score, cutoff_iso, limit),
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

    def get_price_trend(self, uid: str) -> dict:
        """Devuelve la tendencia de precio de una propiedad a partir del
        ├║ltimo cambio registrado en ``price_history``.

        El historial guarda cada cambio como (old_price, new_price); el registro
        m├ís reciente de la propiedad describe su variaci├│n de precio actual.

        Returns:
            dict con:
              - ``previous_price``: precio anterior al ├║ltimo cambio (int) o None
              - ``price_change``: diferencia en euros (new - old) o None
              - ``price_change_pct``: porcentaje de cambio redondeado o None
              - ``trend``: 'down' | 'up' | 'stable' | None (None si no hay historial)
        """
        row = self._conn.execute(
            "SELECT old_price, new_price, delta_pct FROM price_history "
            "WHERE property_uid = ? ORDER BY detected_at DESC, id DESC LIMIT 1",
            (uid,),
        ).fetchone()

        if row is None:
            return {
                "previous_price": None,
                "price_change": None,
                "price_change_pct": None,
                "trend": None,
            }

        old_price = row["old_price"]
        new_price = row["new_price"]
        price_change = new_price - old_price

        if price_change < 0:
            trend = "down"
        elif price_change > 0:
            trend = "up"
        else:
            trend = "stable"

        return {
            "previous_price": old_price,
            "price_change": price_change,
            "price_change_pct": round(row["delta_pct"], 2),
            "trend": trend,
        }

    def count_properties(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM properties").fetchone()[0]

    def count_by_zone(self) -> dict[str, int]:
        rows = self._conn.execute(
            "SELECT zone_id, COUNT(*) as cnt FROM properties GROUP BY zone_id"
        ).fetchall()
        return {r["zone_id"]: r["cnt"] for r in rows}

    def count_radar_properties(self, min_score: float = 55.0) -> int:
        """Cuenta solo las propiedades en el radar.

        Una propiedad esta "en el radar" si su score pasa el threshold de
        alerta y no ha sido descartada, igual que :meth:`get_radar_properties`.
        A diferencia de :meth:`count_properties` (que cuenta TODAS las
        propiedades monitorizadas), esto refleja las que realmente interesan.
        """
        return self._conn.execute(
            "SELECT COUNT(*) FROM scored_properties s "
            "JOIN properties p ON p.uid = s.property_uid "
            "WHERE s.score_total >= ? AND s.dismissed = 0",
            (min_score,),
        ).fetchone()[0]

    def count_by_zone_radar(self, min_score: float = 55.0) -> dict[str, int]:
        """Cuenta por zona solo las propiedades en el radar.

        Mismo filtro que :meth:`count_radar_properties` (score por encima del
        threshold y no descartadas), agrupado por ``zone_id``.
        """
        rows = self._conn.execute(
            "SELECT p.zone_id, COUNT(*) as cnt FROM scored_properties s "
            "JOIN properties p ON p.uid = s.property_uid "
            "WHERE s.score_total >= ? AND s.dismissed = 0 "
            "GROUP BY p.zone_id",
            (min_score,),
        ).fetchall()
        return {r["zone_id"]: r["cnt"] for r in rows}

    # ------------------------------------------------------------------
    # An├ílisis precio/m┬▓ vs media de zona
    # ------------------------------------------------------------------

    def get_zone_avg_price_per_m2(self, zone_id: str) -> float | None:
        """Media de precio/m┬▓ de las propiedades activas (no descartadas) de la zona.

        Solo considera propiedades con ``size_m2`` positivo (necesario para
        calcular el precio por metro cuadrado). Devuelve ``None`` si la zona no
        tiene ninguna propiedad con metros cuadrados v├ílidos.

        Las propiedades descartadas (``scored_properties.dismissed = 1``) se
        excluyen para que la media refleje el mercado vigente del radar.
        """
        row = self._conn.execute(
            """SELECT AVG(p.price * 1.0 / p.size_m2) AS avg_ppm2
               FROM properties p
               LEFT JOIN scored_properties s ON s.property_uid = p.uid
               WHERE p.zone_id = ?
                 AND p.size_m2 IS NOT NULL
                 AND p.size_m2 > 0
                 AND COALESCE(s.dismissed, 0) = 0""",
            (zone_id,),
        ).fetchone()
        avg = row["avg_ppm2"] if row else None
        return round(avg, 2) if avg is not None else None

    def get_price_per_m2_analysis(self, uid: str) -> dict:
        """Analiza el precio/m┬▓ de una propiedad frente a la media de su zona.

        Devuelve un dict con:
          - ``price_per_m2``: precio/m┬▓ de esta propiedad (``None`` si no hay m┬▓)
          - ``zone_avg_price_per_m2``: media de la zona (``None`` si no hay datos)
          - ``below_zone_avg``: ``True`` si el precio/m┬▓ est├í por debajo de la
            media de la zona (``None`` si falta alg├║n dato para comparar)
          - ``pct_vs_zone_avg``: porcentaje respecto a la media; negativo = m├ís
            barato que la media (ej. ``-15.0`` = 15% m├ís barato), positivo = m├ís
            caro. ``None`` si falta alg├║n dato.

        Si el ``uid`` no existe, todos los campos son ``None``.
        """
        empty = {
            "price_per_m2": None,
            "zone_avg_price_per_m2": None,
            "below_zone_avg": None,
            "pct_vs_zone_avg": None,
        }

        row = self._conn.execute(
            "SELECT zone_id, price, size_m2 FROM properties WHERE uid = ?",
            (uid,),
        ).fetchone()
        if row is None:
            return empty

        size_m2 = row["size_m2"]
        price = row["price"]
        if not size_m2 or size_m2 <= 0:
            # Sin metros cuadrados no se puede calcular precio/m┬▓
            return empty

        price_per_m2 = round(price / size_m2, 2)
        zone_avg = self.get_zone_avg_price_per_m2(row["zone_id"])

        return self._build_price_per_m2_dict(price_per_m2, zone_avg)

    @staticmethod
    def _build_price_per_m2_dict(
        price_per_m2: float | None, zone_avg: float | None
    ) -> dict:
        """Construye el dict de an├ílisis a partir de precio/m┬▓ y media de zona.

        Reutilizable por ``get_price_per_m2_analysis`` y por el enriquecido del
        radar, donde el precio/m┬▓ y la media de zona ya se han calculado.
        """
        if price_per_m2 is None or zone_avg is None or zone_avg <= 0:
            return {
                "price_per_m2": price_per_m2,
                "zone_avg_price_per_m2": zone_avg,
                "below_zone_avg": None,
                "pct_vs_zone_avg": None,
            }
        pct = round((price_per_m2 - zone_avg) / zone_avg * 100, 1)
        return {
            "price_per_m2": price_per_m2,
            "zone_avg_price_per_m2": zone_avg,
            "below_zone_avg": price_per_m2 < zone_avg,
            "pct_vs_zone_avg": pct,
        }

    # ------------------------------------------------------------------
    # Series temporales por zona (zone trends)
    # ------------------------------------------------------------------

    def get_zone_trends(self, days: int = 30) -> list[dict]:
        """Devuelve series temporales por zona para gráficas del dashboard."""
        days = max(int(days), 1)
        cutoff_iso = (datetime.now() - timedelta(days=days)).isoformat()
        midpoint_date = (datetime.now() - timedelta(days=days / 2)).isoformat()[:10]

        try:
            from zones import ZONES

            zone_names = {zid: z.name for zid, z in ZONES.items()}
        except Exception:  # pragma: no cover
            zone_names = {}

        rows = self._conn.execute(
            """SELECT p.zone_id AS zone_id,
                      substr(p.first_seen, 1, 10) AS day,
                      COUNT(*) AS cnt,
                      AVG(p.price) AS avg_price,
                      AVG(s.score_total) AS avg_score
               FROM properties p
               LEFT JOIN scored_properties s ON s.property_uid = p.uid
               WHERE p.first_seen >= ?
               GROUP BY p.zone_id, day
               ORDER BY p.zone_id, day""",
            (cutoff_iso,),
        ).fetchall()

        radar_rows = self._conn.execute(
            """SELECT zone_id, COUNT(*) AS cnt
               FROM scored_properties
               WHERE dismissed = 0
               GROUP BY zone_id""",
        ).fetchall()
        radar_by_zone = {r["zone_id"]: r["cnt"] for r in radar_rows}

        points_by_zone: dict[str, list[dict]] = {}
        for r in rows:
            points_by_zone.setdefault(r["zone_id"], []).append(
                {
                    "date": r["day"],
                    "count": r["cnt"],
                    "avg_price": round(r["avg_price"], 2)
                    if r["avg_price"] is not None
                    else None,
                    "avg_score": round(r["avg_score"], 2)
                    if r["avg_score"] is not None
                    else None,
                }
            )

        result: list[dict] = []
        for zone_id, data_points in points_by_zone.items():
            result.append(
                {
                    "zone_id": zone_id,
                    "zone_name": zone_names.get(zone_id, zone_id),
                    "data_points": data_points,
                    "total_properties": radar_by_zone.get(zone_id, 0),
                    "trend": self._compute_trend(data_points, midpoint_date),
                }
            )

        result.sort(key=lambda z: z["zone_id"])
        return result

    @staticmethod
    def _compute_trend(data_points: list[dict], midpoint_date: str) -> str:
        """Clasifica la tendencia comparando primera vs segunda mitad de la ventana."""
        if len(data_points) < 2:
            return "stable"
        first_half = sum(
            dp["count"] for dp in data_points if dp["date"] < midpoint_date
        )
        second_half = sum(
            dp["count"] for dp in data_points if dp["date"] >= midpoint_date
        )
        if second_half > first_half:
            return "growing"
        if second_half < first_half:
            return "declining"
        return "stable"

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
        logger.info("[db] Conexi├│n cerrada")

"""External API proxy routes.

Proxies requests to external services like flood risk and fire data.
"""

import asyncio
import re
import statistics
from datetime import date

import httpx
from fastapi import APIRouter

router = APIRouter(prefix="/api/proxy", tags=["Proxy"])

# Injected by main.py lifespan
FIRMS_MAP_KEY: str = ""


@router.get("/flood")
async def proxy_flood(lat: float, lon: float):
    """Flood risk analysis for a coordinate.

    Source 1: SNCZI MITECO (official Spain) — fluvial hazard T=10/100/500 years.
    Source 2: GloFAS via Open-Meteo Flood API — daily river discharge.

    Response:
      {
        snczi: { t10, t100, t500 } | null,
        glofas: { mean_m3s, max_hist_m3s, p95_m3s, p99_m3s } | null,
        risk_level: "muy_alto"|"alto"|"moderado"|"bajo"|"sin_datos",
        risk_source: "snczi"|"glofas"|"sin_datos",
        calado_m: float | null,
      }
    """
    WMS_BASE = "https://servicios.idee.es/wms-inspire/riesgos-naturales/inundaciones"
    LAYERS = ["NZ.Flood.FluvialT10", "NZ.Flood.FluvialT100", "NZ.Flood.FluvialT500"]
    DELTAS = [0.0005, 0.001, 0.002, 0.005, 0.01, 0.02]
    FILL_VALS = {-9999.0, -3.0}

    def _is_fill(v: float) -> bool:
        if v is None:
            return True
        if v in FILL_VALS or v < -2:
            return True
        return abs(v - 3.4) < 0.1

    async def _wms_query(layer: str, delta: float) -> float | None:
        bbox = (
            f"{lon - delta:.5f},{lat - delta:.5f},{lon + delta:.5f},{lat + delta:.5f}"
        )
        url = (
            f"{WMS_BASE}?SERVICE=WMS&VERSION=1.1.1&REQUEST=GetFeatureInfo"
            f"&BBOX={bbox}&WIDTH=10&HEIGHT=10"
            f"&LAYERS={layer}&QUERY_LAYERS={layer}"
            f"&INFO_FORMAT=text/plain&X=5&Y=5&SRS=EPSG:4326"
        )
        try:
            async with httpx.AsyncClient(timeout=8) as c:
                r = await c.get(url)
            m = re.search(r"GRAY_INDEX\s*=\s*([-\d.]+)", r.text)
            return float(m.group(1)) if m else None
        except Exception:
            return None

    async def _snczi_with_progressive_bbox() -> dict | None:
        for delta in DELTAS:
            results = await asyncio.gather(
                *[_wms_query(layer, delta) for layer in LAYERS]
            )
            t10_raw, t100_raw, t500_raw = results
            t10 = None if _is_fill(t10_raw) else round(t10_raw, 2)
            t100 = None if _is_fill(t100_raw) else round(t100_raw, 2)
            t500 = None if _is_fill(t500_raw) else round(t500_raw, 2)
            if (
                t10 is not None
                and t100 is not None
                and t500 is not None
                and t10 == t100 == t500
            ):
                t10 = t100 = t500 = None
            if any(v is not None for v in (t10, t100, t500)):
                return {
                    "t10": t10,
                    "t100": t100,
                    "t500": t500,
                    "bbox_delta_deg": delta,
                    "bbox_radius_m": int(delta * 111000),
                }
        return None

    async def _glofas() -> dict | None:
        end_date = date.today().isoformat()
        start_date = f"{date.today().year - 30}-01-01"
        url = (
            f"https://flood-api.open-meteo.com/v1/flood?"
            f"latitude={lat}&longitude={lon}&daily=river_discharge"
            f"&start_date={start_date}&end_date={end_date}&cell_selection=nearest"
        )
        try:
            async with httpx.AsyncClient(timeout=15) as c:
                r = await c.get(url)
            d = r.json()
            if not d.get("daily"):
                return None
            vals = [v for v in d["daily"]["river_discharge"] if v is not None]
            if len(vals) < 30:
                return None
            vals_sorted = sorted(vals)
            n = len(vals_sorted)
            return {
                "mean_m3s": round(statistics.mean(vals), 1),
                "max_hist_m3s": round(max(vals), 1),
                "p95_m3s": round(vals_sorted[int(n * 0.95)], 1),
                "p99_m3s": round(vals_sorted[int(n * 0.99)], 1),
                "lat_grid": d.get("latitude"),
                "lon_grid": d.get("longitude"),
                "years": 30,
            }
        except Exception:
            return None

    snczi_data, glofas_data = await asyncio.gather(
        _snczi_with_progressive_bbox(), _glofas()
    )

    risk_level = "sin_datos"
    risk_source = "sin_datos"
    calado_m = None

    if snczi_data:
        t10, t100, t500 = snczi_data["t10"], snczi_data["t100"], snczi_data["t500"]
        if t10 is not None and t10 >= 0:
            risk_level, calado_m = "muy_alto", t10
        elif t100 is not None and t100 >= 0:
            risk_level, calado_m = "alto", t100
        elif t500 is not None and t500 >= 0:
            risk_level, calado_m = "moderado", t500
        else:
            risk_level = "bajo"
        risk_source = "snczi"
    elif glofas_data:
        p99, mx = glofas_data["p99_m3s"], glofas_data["max_hist_m3s"]
        if mx > 1500 or p99 > 500:
            risk_level = "muy_alto"
        elif mx > 500 or p99 > 150:
            risk_level = "alto"
        elif mx > 50 or p99 > 15:
            risk_level = "moderado"
        else:
            risk_level = "bajo"
        risk_source = "glofas"

    return {
        "snczi": snczi_data,
        "glofas": glofas_data,
        "risk_level": risk_level,
        "risk_source": risk_source,
        "calado_m": calado_m,
    }


@router.get("/firms")
async def proxy_firms(lat: float, lon: float):
    """NASA FIRMS fire hotspot proxy — VIIRS SNPP last 3 years.

    Queries high-risk months (June-October) in 5-day blocks.
    """
    if not FIRMS_MAP_KEY:
        return {"status": "no_key", "focos": None}

    delta = 0.27
    bbox = f"{lon - delta:.4f},{lat - delta:.4f},{lon + delta:.4f},{lat + delta:.4f}"
    base = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"
    source = "VIIRS_SNPP_SP"

    today = date.today()
    windows: list[str] = []

    for years_back in range(1, 4):
        year = today.year - years_back
        for month in (6, 7, 8, 9, 10):
            for day_start in range(1, 29, 5):
                try:
                    d = date(year, month, day_start)
                    if d < date(2012, 1, 19) or d >= today:
                        continue
                    windows.append(d.strftime("%Y-%m-%d"))
                except ValueError:
                    pass

    if not windows:
        return {"status": "error", "focos": None, "error": "No available windows"}

    async def _fetch_window(start_date: str) -> int:
        url = f"{base}/{FIRMS_MAP_KEY}/{source}/{bbox}/5/{start_date}"
        try:
            async with httpx.AsyncClient(timeout=12) as client:
                r = await client.get(url)
            if r.status_code != 200:
                return 0
            raw_lines = r.text.strip().split("\n")
            if not raw_lines or len(raw_lines) < 2:
                return 0
            header = raw_lines[0].split(",")
            try:
                ci = header.index("confidence")
            except ValueError:
                ci = None
            count = 0
            for line in raw_lines[1:]:
                if not line.strip():
                    continue
                if ci is not None:
                    parts = line.split(",")
                    if len(parts) > ci and parts[ci].strip().lower() == "l":
                        continue
                count += 1
            return count
        except Exception:
            return 0

    results = await asyncio.gather(*[_fetch_window(w) for w in windows])
    total_focos = sum(results)

    return {
        "status": "ok",
        "focos": total_focos,
        "radio_km": 30,
        "periodo": "jun-oct ultimos 3 anos",
        "peticiones": len(windows),
    }

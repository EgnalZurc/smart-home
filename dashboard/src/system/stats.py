"""System resource statistics endpoint.

Provides Raspberry Pi resource usage (RAM, CPU, disk, temperature).
Only accessible to SUPER profile.
"""

import asyncio
import os

from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/api/system", tags=["System"])


def _require_super(request: Request) -> str:
    """Return username if caller has level 0 (SUPER), raise 403 otherwise."""
    import auth as auth_core
    import user_profiles

    user = auth_core.get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Not authenticated")
    if not user_profiles.is_super(user):
        raise HTTPException(status_code=403, detail="SUPER profile required")
    return user


def _read_cpu_times() -> tuple[float, float]:
    """Read total and idle CPU jiffies from /proc/stat."""
    try:
        line = open("/proc/stat").readline()
        fields = [float(x) for x in line.split()[1:]]
        idle = fields[3] + (fields[4] if len(fields) > 4 else 0)
        total = sum(fields)
        return total, idle
    except Exception:
        return 0.0, 0.0


@router.get("/stats")
async def get_system_stats(request: Request):
    """Return Raspberry Pi system resource usage.

    Reads from /proc/meminfo, /proc/stat, statvfs('/'), and the SoC thermal zone.

    Response:
    {
      "ram":  {"total_mb": int, "used_mb": int, "available_mb": int, "percent": float},
      "swap": {"total_mb": int, "used_mb": int, "percent": float},
      "cpu":  {"percent": float},
      "disk": {"total_gb": float, "used_gb": float, "free_gb": float, "percent": float},
      "temp": {"celsius": float},
    }
    """
    _require_super(request)

    stats: dict = {}

    # ── RAM ──────────────────────────────────────────────────────────────────
    try:
        mem: dict[str, int] = {}
        for line in open("/proc/meminfo"):
            parts = line.split()
            if len(parts) >= 2:
                mem[parts[0].rstrip(":")] = int(parts[1])
        total_kb = mem.get("MemTotal", 0)
        avail_kb = mem.get("MemAvailable", 0)
        free_kb = mem.get("MemFree", 0)
        buffers_kb = mem.get("Buffers", 0)
        cached_kb = (
            mem.get("Cached", 0) + mem.get("SReclaimable", 0) - mem.get("Shmem", 0)
        )
        used_kb = total_kb - free_kb - buffers_kb - max(0, cached_kb)
        stats["ram"] = {
            "total_mb": round(total_kb / 1024),
            "used_mb": round(used_kb / 1024),
            "available_mb": round(avail_kb / 1024),
            "cache_mb": round((buffers_kb + max(0, cached_kb)) / 1024),
            "percent": round(used_kb / total_kb * 100, 1) if total_kb else 0.0,
        }
        swap_total = mem.get("SwapTotal", 0)
        swap_free = mem.get("SwapFree", 0)
        swap_used = swap_total - swap_free
        stats["swap"] = {
            "total_mb": round(swap_total / 1024),
            "used_mb": round(swap_used / 1024),
            "percent": round(swap_used / swap_total * 100, 1) if swap_total else 0.0,
        }
    except Exception as e:
        stats["ram"] = {"error": str(e)}
        stats["swap"] = {"error": str(e)}

    # ── CPU (0.5-second sample) ──────────────────────────────────────────────
    try:
        t1, i1 = _read_cpu_times()
        await asyncio.sleep(0.5)
        t2, i2 = _read_cpu_times()
        dt = t2 - t1
        di = i2 - i1
        cpu_pct = round((1.0 - di / dt) * 100, 1) if dt > 0 else 0.0
        stats["cpu"] = {"percent": cpu_pct}
    except Exception as e:
        stats["cpu"] = {"error": str(e)}

    # ── Disk ─────────────────────────────────────────────────────────────────
    try:
        sv = os.statvfs("/")
        total_b = sv.f_frsize * sv.f_blocks
        free_b = sv.f_frsize * sv.f_bavail
        used_b = total_b - free_b
        GB = 1024**3
        stats["disk"] = {
            "total_gb": round(total_b / GB, 1),
            "used_gb": round(used_b / GB, 1),
            "free_gb": round(free_b / GB, 1),
            "percent": round(used_b / total_b * 100, 1) if total_b else 0.0,
        }
    except Exception as e:
        stats["disk"] = {"error": str(e)}

    # ── Temperature ──────────────────────────────────────────────────────────
    try:
        raw = int(open("/sys/class/thermal/thermal_zone0/temp").read().strip())
        stats["temp"] = {"celsius": round(raw / 1000, 1)}
    except Exception as e:
        stats["temp"] = {"error": str(e)}

    return stats

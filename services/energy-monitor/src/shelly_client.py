"""HTTP client for Shelly EM energy meters (Gen1 + Gen2).

The collector (``collector.py``) polls one :class:`ShellyEMClient` per device
from the inventory in ``ENERGY_DEVICES`` (design §3). Both Shelly generations
expose a local HTTP API — no cloud — so the client talks straight to the device
IP on the LAN:

- **Gen1** (Shelly EM / 3EM, firmware ``mg``): a flat REST API.
  ``GET /status`` returns ``{"emeters": [{power, voltage, pf, total, ...}], ...}``.
  Optional HTTP *Basic* auth.
- **Gen2** (Shelly Pro EM / Pro 3EM, firmware ``gen2``): JSON-RPC over HTTP.
  ``GET /rpc/Shelly.GetStatus`` returns one document with ``em:0`` (instantaneous
  power/voltage/pf) and ``emdata:0`` (cumulative Wh counters). Optional HTTP
  *Digest* auth.

Both are normalised to the same shape so the collector never branches on
generation:

    get_power()  -> {"ch0": {"power": W, "voltage": V, "pf": pf}, ...}
    get_energy() -> {"ch0": energy_wh, ...}          # monotonic Wh counter
    get_status() -> {"online": bool, "power": {...}, "energy": {...},
                     "device_id": str, "gen": int}

Channel keys (``ch0``, ``ch1``, ...) match the ``channels`` map in the device
inventory so labels resolve consistently across power + energy.

The client is async (``httpx.AsyncClient``) because the collector runs inside
the FastAPI event loop and polls several devices concurrently; a blocking client
would stall the loop (same reasoning as metrics-service's collector).
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger: logging.Logger = logging.getLogger(__name__)

# Shelly generation identifiers used across the inventory + client.
GEN1: int = 1
GEN2: int = 2


class ShellyError(Exception):
    """Raised when a Shelly device cannot be reached or returns bad data."""


class ShellyEMClient:
    """Local-HTTP client for a single Shelly EM device (Gen1 or Gen2).

    Args:
        device_id: Stable id from the inventory (used as a log/label prefix).
        ip: Device IP or hostname on the LAN.
        gen: Shelly generation (``1`` or ``2``). Defaults to Gen1.
        channels: Optional ``{"ch0": "label", ...}`` map. When omitted the
            client reports whatever channels the device exposes as ``ch0..chN``.
        username / password: Optional device credentials. Gen1 uses HTTP Basic,
            Gen2 uses Digest; httpx picks the scheme from the device's challenge.
        timeout: Per-request timeout in seconds.
        client: Optional shared ``httpx.AsyncClient`` (tests inject a mock
            transport). When omitted the client owns a private one.
    """

    def __init__(
        self,
        device_id: str,
        ip: str,
        gen: int = GEN1,
        channels: dict[str, str] | None = None,
        username: str | None = None,
        password: str | None = None,
        timeout: float = 4.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.device_id: str = device_id
        self.ip: str = ip
        self.gen: int = gen
        self.channels: dict[str, str] = channels or {}
        self._timeout: float = timeout
        self._auth: httpx.Auth | None = None
        if username and password:
            # httpx.DigestAuth also works against Basic challenges, but Gen1
            # devices only speak Basic, so pick per generation explicitly.
            if gen == GEN2:
                self._auth = httpx.DigestAuth(username, password)
            else:
                self._auth = httpx.BasicAuth(username, password)
        self._owns_client: bool = client is None
        self._client: httpx.AsyncClient = client or httpx.AsyncClient(timeout=timeout)

    @property
    def base_url(self) -> str:
        """Return the device's base URL (``http://<ip>``)."""
        return f"http://{self.ip}"

    # ── Low-level fetch ───────────────────────────────────────────────────────
    async def _get_json(self, path: str) -> dict[str, Any]:
        """GET a JSON document from the device, raising ShellyError on failure."""
        url: str = f"{self.base_url}{path}"
        try:
            resp: httpx.Response = await self._client.get(
                url, auth=self._auth, timeout=self._timeout
            )
            resp.raise_for_status()
            return resp.json()  # type: ignore[no-any-return]
        except (httpx.HTTPError, ValueError) as exc:
            raise ShellyError(f"{self.device_id}: GET {path} failed: {exc}") from exc

    async def get_status(self) -> dict[str, Any]:
        """Return a normalised snapshot of the device.

        Shape::

            {
                "device_id": str,
                "gen": int,
                "online": bool,
                "power":  {"ch0": {"power", "voltage", "pf"}, ...},
                "energy": {"ch0": energy_wh, ...},
            }

        ``online`` is ``False`` (and power/energy empty) when the device is
        unreachable or returns malformed data — the collector treats that as a
        missed tick rather than crashing.
        """
        try:
            if self.gen == GEN2:
                power, energy = await self._status_gen2()
            else:
                power, energy = await self._status_gen1()
        except ShellyError as exc:
            logger.warning("Shelly %s offline: %s", self.device_id, exc)
            return {
                "device_id": self.device_id,
                "gen": self.gen,
                "online": False,
                "power": {},
                "energy": {},
            }
        return {
            "device_id": self.device_id,
            "gen": self.gen,
            "online": True,
            "power": power,
            "energy": energy,
        }

    async def get_power(self) -> dict[str, dict[str, float | None]]:
        """Return instantaneous power per channel (empty dict if offline)."""
        status: dict[str, Any] = await self.get_status()
        return status["power"]  # type: ignore[no-any-return]

    async def get_energy(self) -> dict[str, float]:
        """Return the cumulative Wh counter per channel (empty dict if offline)."""
        status: dict[str, Any] = await self.get_status()
        return status["energy"]  # type: ignore[no-any-return]

    # ── Channel labelling ─────────────────────────────────────────────────────
    def _channel_key(self, index: int) -> str:
        """Map a meter index to its inventory channel key (``ch{index}``)."""
        return f"ch{index}"

    # ── Gen1 (flat REST /status) ──────────────────────────────────────────────
    async def _status_gen1(
        self,
    ) -> tuple[dict[str, dict[str, float | None]], dict[str, float]]:
        """Parse the Gen1 ``/status`` payload into (power, energy) maps."""
        data: dict[str, Any] = await self._get_json("/status")
        emeters: Any = data.get("emeters")
        if not isinstance(emeters, list) or not emeters:
            raise ShellyError("no emeters in /status payload")
        power: dict[str, dict[str, float | None]] = {}
        energy: dict[str, float] = {}
        for idx, em in enumerate(emeters):
            if not isinstance(em, dict):
                continue
            key: str = self._channel_key(idx)
            power[key] = {
                "power": _as_float(em.get("power")),
                "voltage": _as_float(em.get("voltage")),
                "pf": _as_float(em.get("pf")),
            }
            # Gen1 reports cumulative "total" (consumed) in Wh.
            total: float | None = _as_float(em.get("total"))
            if total is not None:
                energy[key] = total
        return power, energy

    # ── Gen2 (JSON-RPC /rpc/Shelly.GetStatus) ─────────────────────────────────
    async def _status_gen2(
        self,
    ) -> tuple[dict[str, dict[str, float | None]], dict[str, float]]:
        """Parse the Gen2 ``Shelly.GetStatus`` RPC into (power, energy) maps.

        Gen2 EM components come in two flavours:

        - 3-phase ``em:N`` (Shelly Pro 3EM): per-phase ``a_/b_/c_act_power``,
          mapped to ``ch0/ch1/ch2``; cumulative Wh lives under ``emdata:N``.
        - single ``em1:N`` (Shelly Pro EM, two independent meters): one
          ``act_power`` each, mapped to ``ch0``, ``ch1``, ...; Wh under
          ``em1data:N``.
        """
        data: dict[str, Any] = await self._get_json("/rpc/Shelly.GetStatus")
        power: dict[str, dict[str, float | None]] = {}
        energy: dict[str, float] = {}

        # 3-phase EM component (keys like "em:0").
        for comp_key, comp in data.items():
            if not isinstance(comp, dict):
                continue
            if comp_key.startswith("em:"):
                self._parse_gen2_em3(comp, power)
            elif comp_key.startswith("em1:"):
                self._parse_gen2_em1(comp_key, comp, power)
            elif comp_key.startswith("emdata:"):
                self._parse_gen2_emdata3(comp, energy)
            elif comp_key.startswith("em1data:"):
                self._parse_gen2_emdata1(comp_key, comp, energy)

        if not power:
            raise ShellyError("no em/em1 components in Shelly.GetStatus payload")
        return power, energy

    def _parse_gen2_em3(
        self, comp: dict[str, Any], power: dict[str, dict[str, float | None]]
    ) -> None:
        """Map a 3-phase ``em:N`` component to ch0/ch1/ch2 power entries."""
        for idx, phase in enumerate(("a", "b", "c")):
            act: Any = comp.get(f"{phase}_act_power")
            if act is None:
                continue
            power[self._channel_key(idx)] = {
                "power": _as_float(act),
                "voltage": _as_float(comp.get(f"{phase}_voltage")),
                "pf": _as_float(comp.get(f"{phase}_pf")),
            }

    def _parse_gen2_em1(
        self,
        comp_key: str,
        comp: dict[str, Any],
        power: dict[str, dict[str, float | None]],
    ) -> None:
        """Map a single ``em1:N`` component to a ``chN`` power entry."""
        idx: int | None = _rpc_index(comp_key)
        if idx is None:
            return
        power[self._channel_key(idx)] = {
            "power": _as_float(comp.get("act_power")),
            "voltage": _as_float(comp.get("voltage")),
            "pf": _as_float(comp.get("pf")),
        }

    def _parse_gen2_emdata3(
        self, comp: dict[str, Any], energy: dict[str, float]
    ) -> None:
        """Map a 3-phase ``emdata:N`` component to ch0/ch1/ch2 Wh counters."""
        for idx, phase in enumerate(("a", "b", "c")):
            wh: float | None = _as_float(comp.get(f"{phase}_total_act_energy"))
            if wh is not None:
                energy[self._channel_key(idx)] = wh

    def _parse_gen2_emdata1(
        self, comp_key: str, comp: dict[str, Any], energy: dict[str, float]
    ) -> None:
        """Map a single ``em1data:N`` component to a ``chN`` Wh counter."""
        idx: int | None = _rpc_index(comp_key)
        if idx is None:
            return
        wh: float | None = _as_float(comp.get("total_act_energy"))
        if wh is not None:
            energy[self._channel_key(idx)] = wh

    # ── Lifecycle ─────────────────────────────────────────────────────────────
    async def aclose(self) -> None:
        """Close the private HTTP client (no-op for an injected shared one)."""
        if self._owns_client:
            await self._client.aclose()


def _as_float(value: Any) -> float | None:
    """Coerce a value to float, returning None for missing/invalid input."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _rpc_index(comp_key: str) -> int | None:
    """Extract the integer index from an RPC key like ``em1:2`` → ``2``."""
    try:
        return int(comp_key.split(":", 1)[1])
    except (IndexError, ValueError):
        return None

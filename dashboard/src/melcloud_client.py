"""Client for the MELCloud API.

Works with both the real API and the POC mock.
The base URL is configured via the MELCLOUD_URL environment variable.
"""

import logging
import time

import httpx

logger = logging.getLogger(__name__)

AC_MODE_HEAT = 1
AC_MODE_DRY = 2
AC_MODE_COOL = 3
AC_MODE_FAN = 7
AC_MODE_AUTO = 8

MODE_MAP = {
    "heat": AC_MODE_HEAT,
    "dry": AC_MODE_DRY,
    "cool": AC_MODE_COOL,
    "fan": AC_MODE_FAN,
    "auto": AC_MODE_AUTO,
}


class MelCloudClient:
    """HTTP client for the MELCloud API."""

    def __init__(
        self, 
        base_url: str, 
        email: str, 
        password: str, 
        building_id: int = 0,
        timeout: float = 30.0,
        app_version: str = "1.32.1.0"
    ):
        # Normalize: if the URL already includes the base path, use it as is.
        # Otherwise, add it.
        base = base_url.rstrip("/")
        if base.endswith("/Mitsubishi.Wifi.Client"):
            self.base_url = base
        else:
            self.base_url = f"{base}/Mitsubishi.Wifi.Client"
        self.email = email
        self.password = password  # Will be deleted after login
        self._building_id = building_id
        self._timeout = timeout
        self._app_version = app_version
        self.context_key: str | None = None
        self.client = httpx.Client(timeout=timeout)

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.context_key:
            headers["X-MitsContextKey"] = self.context_key
        return headers

    def login(self) -> bool:
        """Authenticate and get ContextKey."""
        try:
            resp = self.client.post(
                f"{self.base_url}/Login/ClientLogin",
                json={
                    "Email": self.email,
                    "Password": self.password,
                    "Language": 0,
                    "AppVersion": self._app_version,
                    "Persist": True,
                    "CaptchaResponse": None,
                },
                headers=self._headers(),
            )
            resp.raise_for_status()
            data = resp.json()

            if data.get("ErrorId"):
                logger.error("Login failed: %s", data.get("ErrorMessage"))
                return False

            self.context_key = data.get("LoginData", {}).get("ContextKey")
            if not self.context_key:
                logger.error("Login OK but no ContextKey")
                return False

            logger.info("Successful login to MELCloud")
            
            # Security: Delete password from memory after successful login
            del self.password
            
            return True

        except httpx.HTTPError as e:
            logger.error("HTTP error on login: %s", e)
            return False

    def get_device_state(self, device_id: int, building_id: int) -> dict | None:
        """Gets complete AC state (raw dict from API)."""
        try:
            resp = self.client.get(
                f"{self.base_url}/Device/Get",
                params={"id": device_id, "buildingID": building_id},
                headers=self._headers(),
            )
            resp.raise_for_status()
            return resp.json()

        except httpx.HTTPError as e:
            logger.error("Error getting state: %s", e)
            return None

    def set_temperature(
        self,
        device_id: int,
        setpoint: float,
        power: bool = True,
        mode: str = "cool",
        fan_speed: int = 0,
        building_id: int | None = None,
    ) -> bool:
        """Configures the AC.

        Method: GET complete state → modify fields → POST complete state.
        The MELCloud API requires sending the entire device state,
        not just the fields to modify.

        Args:
            device_id: Device ID in MELCloud.
            setpoint: Target temperature (16-31°C).
            power: Turn on/off.
            mode: "cool", "heat", "auto", "dry", "fan".
            fan_speed: 0=auto, 1-5=manual.
            building_id: Building ID (needed for previous GET).
        """
        setpoint = max(16.0, min(31.0, setpoint))
        operation_mode = MODE_MAP.get(mode, AC_MODE_COOL)

        try:
            # 1. Get current complete state
            state = self.get_device_state(device_id, building_id or self._building_id)
            if state is None:
                logger.error("Could not get current state for SetAta")
                return False

            # 2. Modify necessary fields
            state["Power"] = power
            state["OperationMode"] = operation_mode
            state["SetTemperature"] = setpoint
            state["SetFanSpeed"] = fan_speed
            state["EffectiveFlags"] = 0x1F  # Power + Mode + Temp + Fan + Vane
            state["HasPendingCommand"] = True

            # 3. Send modified complete state
            resp = self.client.post(
                f"{self.base_url}/Device/SetAta",
                json=state,
                headers=self._headers(),
            )
            resp.raise_for_status()
            data = resp.json()

            # Verify it was applied
            applied_temp = data.get("SetTemperature")
            if applied_temp != setpoint:
                logger.warning(
                    "SetAta responded with SetTemp=%.1f (expected %.1f). "
                    "May be temporarily offline.",
                    applied_temp or 0, setpoint,
                )

            logger.info(
                "AC configured: power=%s, mode=%s, setpoint=%.1f°C, fan=%d",
                power, mode, setpoint, fan_speed,
            )
            return True

        except httpx.HTTPError as e:
            logger.error("Error configuring AC: %s", e)
            return False

    def close(self):
        """Closes the HTTP client."""
        self.client.close()

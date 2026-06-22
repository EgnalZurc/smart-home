"""Cliente para la API de MELCloud.

Funciona tanto con la API real como con el mock del POC.
La URL base se configura vía variable de entorno MELCLOUD_URL.
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
    """Cliente HTTP para la API de MELCloud."""

    def __init__(self, base_url: str, email: str, password: str, building_id: int = 0):
        # Normalizar: si la URL ya incluye el path base, usarla tal cual.
        # Si no, añadirlo.
        base = base_url.rstrip("/")
        if base.endswith("/Mitsubishi.Wifi.Client"):
            self.base_url = base
        else:
            self.base_url = f"{base}/Mitsubishi.Wifi.Client"
        self.email = email
        self.password = password
        self._building_id = building_id
        self.context_key: str | None = None
        self.client = httpx.Client(timeout=30.0)

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.context_key:
            headers["X-MitsContextKey"] = self.context_key
        return headers

    def login(self) -> bool:
        """Autenticarse y obtener ContextKey."""
        try:
            resp = self.client.post(
                f"{self.base_url}/Login/ClientLogin",
                json={
                    "Email": self.email,
                    "Password": self.password,
                    "Language": 0,
                    "AppVersion": "1.32.1.0",
                    "Persist": True,
                    "CaptchaResponse": None,
                },
                headers=self._headers(),
            )
            resp.raise_for_status()
            data = resp.json()

            if data.get("ErrorId"):
                logger.error("Login fallido: %s", data.get("ErrorMessage"))
                return False

            self.context_key = data.get("LoginData", {}).get("ContextKey")
            if not self.context_key:
                logger.error("Login OK pero sin ContextKey")
                return False

            logger.info("Login exitoso en MELCloud")
            return True

        except httpx.HTTPError as e:
            logger.error("Error HTTP en login: %s", e)
            return False

    def get_device_state(self, device_id: int, building_id: int) -> dict | None:
        """Obtiene el estado completo del AC (dict raw de la API)."""
        try:
            resp = self.client.get(
                f"{self.base_url}/Device/Get",
                params={"id": device_id, "buildingID": building_id},
                headers=self._headers(),
            )
            resp.raise_for_status()
            return resp.json()

        except httpx.HTTPError as e:
            logger.error("Error obteniendo estado: %s", e)
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
        """Configura el AC.

        Método: GET estado completo → modificar campos → POST estado completo.
        La API de MELCloud requiere enviar el estado entero del dispositivo,
        no solo los campos a modificar.

        Args:
            device_id: ID del dispositivo en MELCloud.
            setpoint: Temperatura objetivo (16-31°C).
            power: Encender/apagar.
            mode: "cool", "heat", "auto", "dry", "fan".
            fan_speed: 0=auto, 1-5=manual.
            building_id: ID del building (necesario para GET previo).
        """
        setpoint = max(16.0, min(31.0, setpoint))
        operation_mode = MODE_MAP.get(mode, AC_MODE_COOL)

        try:
            # 1. Obtener estado actual completo
            state = self.get_device_state(device_id, building_id or self._building_id)
            if state is None:
                logger.error("No se pudo obtener estado actual para SetAta")
                return False

            # 2. Modificar los campos necesarios
            state["Power"] = power
            state["OperationMode"] = operation_mode
            state["SetTemperature"] = setpoint
            state["SetFanSpeed"] = fan_speed
            state["EffectiveFlags"] = 0x1F  # Power + Mode + Temp + Fan + Vane
            state["HasPendingCommand"] = True

            # 3. Enviar estado completo modificado
            resp = self.client.post(
                f"{self.base_url}/Device/SetAta",
                json=state,
                headers=self._headers(),
            )
            resp.raise_for_status()
            data = resp.json()

            # Verificar que se aplicó
            applied_temp = data.get("SetTemperature")
            if applied_temp != setpoint:
                logger.warning(
                    "SetAta respondió con SetTemp=%.1f (esperado %.1f). "
                    "Puede estar offline temporalmente.",
                    applied_temp or 0, setpoint,
                )

            logger.info(
                "AC configurado: power=%s, mode=%s, setpoint=%.1f°C, fan=%d",
                power, mode, setpoint, fan_speed,
            )
            return True

        except httpx.HTTPError as e:
            logger.error("Error configurando AC: %s", e)
            return False

    def close(self):
        """Cierra el cliente HTTP."""
        self.client.close()

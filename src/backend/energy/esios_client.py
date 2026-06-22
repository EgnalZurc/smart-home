"""Cliente para API ESIOS (REE - Red Eléctrica España)."""

import httpx
from datetime import datetime, timedelta
from pathlib import Path
import json
import logging

logger = logging.getLogger(__name__)


class ESIOSClient:
    """Cliente para obtener precios PVPC de la API ESIOS."""
    
    BASE_URL = "https://api.esios.ree.es"
    PVPC_INDICATOR = "1001"  # Precio voluntario pequeño consumidor
    
    def __init__(self, api_key: str, cache_file: Path):
        self.api_key = api_key
        self.cache_file = cache_file
        self._cache = self._load_cache()
    
    def _load_cache(self) -> dict:
        """Carga cache de precios desde disco."""
        if self.cache_file.exists():
            try:
                data = json.loads(self.cache_file.read_text(encoding="utf-8"))
                logger.info(f"Cache de precios ESIOS cargado: {len(data.get('prices', {}))} entradas")
                return data
            except Exception as e:
                logger.warning(f"Error cargando cache ESIOS: {e}")
        return {"last_fetch": 0, "prices": {}}
    
    def _save_cache(self):
        """Guarda cache a disco."""
        try:
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            self.cache_file.write_text(
                json.dumps(self._cache, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
            logger.debug("Cache de precios ESIOS guardado")
        except Exception as e:
            logger.error(f"Error guardando cache ESIOS: {e}")
    
    async def get_price_at(self, timestamp: float) -> float | None:
        """Obtiene precio €/kWh para un timestamp específico.
        
        Args:
            timestamp: Unix timestamp
            
        Returns:
            Precio en €/kWh, o None si no disponible
        """
        dt = datetime.fromtimestamp(timestamp)
        key = dt.strftime("%Y-%m-%dT%H:00:00")
        
        # Verificar cache
        if key in self._cache["prices"]:
            return self._cache["prices"][key]
        
        # Si no está en cache, fetch del día completo
        if self.api_key:
            await self._fetch_day_prices(dt)
            return self._cache["prices"].get(key)
        else:
            logger.warning("API key ESIOS no configurada, usando precio mock")
            return 0.15  # Precio mock para desarrollo
    
    async def _fetch_day_prices(self, date: datetime):
        """Obtiene precios de un día completo desde ESIOS.
        
        Args:
            date: Fecha para la cual obtener precios
        """
        start = date.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        
        url = f"{self.BASE_URL}/indicators/{self.PVPC_INDICATOR}"
        params = {
            "start_date": start.strftime("%Y-%m-%dT%H:%M:%S"),
            "end_date": end.strftime("%Y-%m-%dT%H:%M:%S")
        }
        headers = {"x-api-key": self.api_key}
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(url, params=params, headers=headers, timeout=10.0)
                response.raise_for_status()
                data = response.json()
            
            # Parsear respuesta
            values_count = 0
            for value in data["indicator"]["values"]:
                dt_str = value["datetime"][:16]  # "2026-06-22T00:00"
                price_mwh = value["value"]
                price_kwh = price_mwh / 1000  # MWh → kWh
                self._cache["prices"][dt_str] = price_kwh
                values_count += 1
            
            self._cache["last_fetch"] = datetime.now().timestamp()
            self._save_cache()
            logger.info(f"Precios PVPC actualizados para {start.date()}: {values_count} valores")
        
        except httpx.HTTPStatusError as e:
            logger.error(f"Error HTTP obteniendo precios ESIOS: {e.response.status_code}")
        except Exception as e:
            logger.error(f"Error obteniendo precios ESIOS: {e}")

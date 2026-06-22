"""Seguimiento de consumo energético y coste."""

import time
import json
from pathlib import Path
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


class EnergyTracker:
    """Seguimiento de consumo energético del AC y su coste en euros."""
    
    def __init__(self, ac_controller, esios_client, data_dir: Path):
        """Inicializa el tracker de energía.
        
        Args:
            ac_controller: Instancia de ACController
            esios_client: Cliente para obtener precios PVPC
            data_dir: Directorio donde guardar datos
        """
        self.ac = ac_controller
        self.esios = esios_client
        self.hourly_file = data_dir / "energy_hourly.json"
        self.daily_file = data_dir / "energy_daily.json"
        
        # Acumuladores en memoria (optimización)
        self._current_24h_kwh = 0.0
        self._current_24h_cost = 0.0
        
        # Cargar datos
        self._hourly_data = self._load_json(self.hourly_file, default={"last_update": 0, "data": {}})
        self._daily_data = self._load_json(self.daily_file, default={"last_update": 0, "data": {}})
        
        # Calcular acumuladores desde datos cargados
        self._recalculate_24h_totals()
        
        logger.info("EnergyTracker inicializado: %.3f kWh (€%.2f) en últimas 24h", 
                   self._current_24h_kwh, self._current_24h_cost)
    
    def _load_json(self, path: Path, default: dict) -> dict:
        """Carga JSON desde disco.
        
        Args:
            path: Ruta al archivo JSON
            default: Valor por defecto si no existe
            
        Returns:
            Datos del JSON o default
        """
        if path.exists():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                logger.info(f"Cargado {path.name}: {len(data.get('data', {}))} registros")
                return data
            except Exception as e:
                logger.error(f"Error cargando {path}: {e}")
        return default
    
    def _save_json(self, path: Path, data: dict):
        """Guarda JSON a disco.
        
        Args:
            path: Ruta donde guardar
            data: Datos a guardar
        """
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            logger.debug(f"Guardado {path.name}")
        except Exception as e:
            logger.error(f"Error guardando {path}: {e}")
    
    def _recalculate_24h_totals(self):
        """Recalcula acumuladores 24h desde datos en disco."""
        self._current_24h_kwh = sum(h["kwh"] for h in self._hourly_data["data"].values())
        self._current_24h_cost = sum(h["cost"] for h in self._hourly_data["data"].values())
        logger.debug(f"Acumuladores 24h recalculados: {self._current_24h_kwh:.3f} kWh, €{self._current_24h_cost:.2f}")
    
    async def record_hourly(self):
        """Registra consumo de la última hora (llamado cada :00).
        
        Este método debe ser llamado por el scheduler cada hora en punto.
        """
        now = time.time()
        hour = datetime.fromtimestamp(now).strftime("%H")
        
        logger.info("=== Iniciando registro horario ===")
        
        # Obtener consumo desde último registro
        kwh = self.ac.get_session_kwh()
        logger.info(f"Consumo sesión: {kwh:.4f} kWh")
        
        # Obtener precio de la hora anterior (hora en que se consumió)
        hour_ago = now - 3600
        price_per_kwh = await self.esios.get_price_at(hour_ago)
        if price_per_kwh is None:
            logger.warning("No se pudo obtener precio ESIOS, usando último conocido")
            price_per_kwh = self._get_last_known_price()
        
        logger.info(f"Precio €/kWh: {price_per_kwh:.5f}")
        
        cost = kwh * price_per_kwh
        logger.info(f"Coste: €{cost:.3f}")
        
        # Remover hora que sale del rolling window (hace 24h)
        old_hour_data = self._hourly_data["data"].get(hour)
        if old_hour_data:
            logger.debug(f"Removiendo hora {hour} antigua: {old_hour_data['kwh']:.3f} kWh, €{old_hour_data['cost']:.3f}")
            self._current_24h_kwh -= old_hour_data["kwh"]
            self._current_24h_cost -= old_hour_data["cost"]
        
        # Añadir nueva hora
        self._hourly_data["data"][hour] = {
            "kwh": round(kwh, 3),
            "price_per_kwh": round(price_per_kwh, 5),
            "cost": round(cost, 3),
            "timestamp": int(now)
        }
        self._hourly_data["last_update"] = int(now)
        
        # Actualizar acumuladores
        self._current_24h_kwh += kwh
        self._current_24h_cost += cost
        
        # Guardar
        self._save_json(self.hourly_file, self._hourly_data)
        
        # Resetear sesión del controlador
        self.ac.reset_session_kwh()
        
        logger.info(f"✅ Registro horario completado: {kwh:.3f} kWh @ €{price_per_kwh:.5f}/kWh = €{cost:.3f}")
        logger.info(f"Total 24h: {self._current_24h_kwh:.3f} kWh (€{self._current_24h_cost:.2f})")
    
    async def record_daily(self):
        """Registra consumo del último día (llamado a las 00:00).
        
        Este método debe ser llamado por el scheduler cada día a medianoche.
        """
        now = time.time()
        date_key = datetime.fromtimestamp(now).strftime("%Y-%m-%d")
        
        logger.info("=== Iniciando registro diario ===")
        
        # Sumar todas las horas del día anterior
        kwh_day = sum(h["kwh"] for h in self._hourly_data["data"].values())
        cost_day = sum(h["cost"] for h in self._hourly_data["data"].values())
        
        logger.info(f"Consumo día {date_key}: {kwh_day:.3f} kWh = €{cost_day:.2f}")
        
        # Guardar en daily
        self._daily_data["data"][date_key] = {
            "kwh": round(kwh_day, 3),
            "cost": round(cost_day, 2),
            "timestamp": int(now)
        }
        self._daily_data["last_update"] = int(now)
        
        # Limitar a 365 días (rolling)
        if len(self._daily_data["data"]) > 365:
            # Eliminar el más antiguo
            oldest = min(self._daily_data["data"].keys())
            logger.debug(f"Removiendo día antiguo: {oldest}")
            del self._daily_data["data"][oldest]
        
        self._save_json(self.daily_file, self._daily_data)
        
        logger.info(f"✅ Registro diario completado: {kwh_day:.3f} kWh = €{cost_day:.2f}")
        logger.info(f"Total días en histórico: {len(self._daily_data['data'])}")
    
    def get_current_24h(self) -> dict:
        """Devuelve totales de últimas 24h (desde acumuladores).
        
        Returns:
            Dict con kwh y cost
        """
        return {
            "kwh": round(self._current_24h_kwh, 3),
            "cost": round(self._current_24h_cost, 2)
        }
    
    def get_hourly_stats(self) -> dict:
        """Devuelve datos para gráfica horaria.
        
        Returns:
            Dict con datos por hora (key=HH, value=dict con kwh, price_per_kwh, cost, timestamp)
        """
        return self._hourly_data["data"]
    
    def get_monthly_stats(self) -> dict:
        """Devuelve datos para gráfica mensual (agregado por mes).
        
        Returns:
            Dict con datos por mes (key=YYYY-MM, value=dict con kwh, cost)
        """
        monthly = {}
        for date_key, data in self._daily_data["data"].items():
            month_key = date_key[:7]  # "2026-06"
            if month_key not in monthly:
                monthly[month_key] = {"kwh": 0.0, "cost": 0.0}
            monthly[month_key]["kwh"] += data["kwh"]
            monthly[month_key]["cost"] += data["cost"]
        
        # Redondear
        for month in monthly.values():
            month["kwh"] = round(month["kwh"], 2)
            month["cost"] = round(month["cost"], 2)
        
        return monthly
    
    def _get_last_known_price(self) -> float:
        """Devuelve último precio conocido (fallback).
        
        Returns:
            Precio en €/kWh
        """
        if self._hourly_data["data"]:
            last_entry = list(self._hourly_data["data"].values())[-1]
            price = last_entry.get("price_per_kwh", 0.15)
            logger.debug(f"Usando último precio conocido: €{price:.5f}/kWh")
            return price
        logger.warning("No hay precios conocidos, usando fallback: €0.15/kWh")
        return 0.15  # Fallback: 0.15 €/kWh (precio típico)

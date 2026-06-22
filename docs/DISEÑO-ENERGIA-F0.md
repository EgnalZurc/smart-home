# Diseño: Seguimiento de Energía - Integrado en Fase 0

**Fecha:** 22 de junio de 2026  
**Estado:** 📝 DISEÑO COMPLETO - LISTO PARA IMPLEMENTAR

---

## 🎯 Objetivo

Añadir seguimiento del consumo energético del AC y su coste en euros como parte integral de la Fase 0, mostrando estadísticas por horas (últimas 24h) y por días (últimos 12 meses).

---

## 📊 Nuevo Requerimiento Fase 0

| # | Requerimiento | Prioridad |
|---|---|---|
| **F0.24** | Mostrar consumo energético total (24h) y coste en € en la pantalla principal | 🔴 Alta |
| **F0.25** | Obtener precio de energía regulada (PVPC) de API ESIOS (REE España) cada hora | 🔴 Alta |
| **F0.26** | Registrar consumo cada hora (:00) en JSON con 24 valores (rolling) | 🔴 Alta |
| **F0.27** | Registrar consumo cada día (00:00) en JSON con hasta 365 valores (rolling) | 🟡 Media |
| **F0.28** | Popup de estadísticas energéticas con 2 gráficas (click en widget energía) | 🟡 Media |
| **F0.29** | Calcular coste usando precio exacto del momento de consumo | 🔴 Alta |
| **F0.30** | Optimización: usar acumuladores en memoria, no recalcular siempre | 🟡 Media |

---

## 🏗️ Arquitectura

### Componentes Nuevos

```
src/backend/
├── energy/
│   ├── __init__.py
│   ├── tracker.py          # EnergyTracker (cálculo consumo + tracking)
│   └── esios_client.py     # Cliente API ESIOS (precios PVPC)
├── api/
│   └── routes.py           # Añadir endpoints /api/energy/*
└── main.py                 # Integrar scheduler APScheduler
```

### Archivos de Datos (Persisten en volumen Docker)

```
/app/data/
├── sensor_readings.json        # Ya existe
├── outdoor_reading.json        # Ya existe
├── energy_hourly.json          # NUEVO: 24 horas rolling
├── energy_daily.json           # NUEVO: 365 días rolling
└── energy_prices_cache.json    # NUEVO: Cache precios PVPC
```

---

## 📐 Diseño Detallado

### 1. Cálculo de Consumo

**Método:** Estimación basada en tiempo encendido y potencia AC.

**Potencia del AC:**
- `cooling_max`: 2.5 kW (100%)
- `cooling_mid`: 1.75 kW (70%)
- `modulating`: 1.25 kW (50%)
- Otros estados: 0 kW

**Tracking en `ac_controller.py`:**
```python
# Añadir al ACController
self._energy_state = {
    'last_state': 'off',
    'last_transition': time.time(),
    'kwh_session': 0.0  # kWh acumulados en la sesión actual
}

def _track_energy_transition(self, new_state: str):
    """Registra transición de estado para cálculo energía"""
    now = time.time()
    elapsed_hours = (now - self._energy_state['last_transition']) / 3600
    
    # Calcular consumo del estado anterior
    power_kw = self._get_power_for_state(self._energy_state['last_state'])
    kwh_consumed = power_kw * elapsed_hours
    self._energy_state['kwh_session'] += kwh_consumed
    
    # Actualizar estado
    self._energy_state['last_state'] = new_state
    self._energy_state['last_transition'] = now

def _get_power_for_state(self, state: str) -> float:
    """Devuelve potencia en kW para un estado"""
    power_map = {
        'cooling_max': 2.5,
        'cooling_mid': 1.75,
        'modulating': 1.25,
        'forced_on': 2.5,  # Asumimos máximo
    }
    return power_map.get(state, 0.0)

def get_session_kwh(self) -> float:
    """Devuelve kWh consumidos en la sesión actual (desde último registro)"""
    # Añadir consumo del estado actual hasta ahora
    now = time.time()
    elapsed_hours = (now - self._energy_state['last_transition']) / 3600
    power_kw = self._get_power_for_state(self._energy_state['last_state'])
    current_kwh = power_kw * elapsed_hours
    return self._energy_state['kwh_session'] + current_kwh

def reset_session_kwh(self):
    """Resetea contador de sesión (llamado tras registro horario)"""
    self._energy_state['kwh_session'] = 0.0
    self._energy_state['last_transition'] = time.time()
```

### 2. Cliente API ESIOS

**Archivo:** `src/backend/energy/esios_client.py`

```python
import httpx
from datetime import datetime, timedelta
from pathlib import Path
import json
import logging

logger = logging.getLogger(__name__)

class ESIOSClient:
    """Cliente para API ESIOS (REE - Red Eléctrica España)"""
    
    BASE_URL = "https://api.esios.ree.es"
    PVPC_INDICATOR = "1001"  # Precio voluntario pequeño consumidor
    
    def __init__(self, api_key: str, cache_file: Path):
        self.api_key = api_key
        self.cache_file = cache_file
        self._cache = self._load_cache()
    
    def _load_cache(self) -> dict:
        """Carga cache de precios desde disco"""
        if self.cache_file.exists():
            try:
                return json.loads(self.cache_file.read_text())
            except:
                pass
        return {"last_fetch": 0, "prices": {}}
    
    def _save_cache(self):
        """Guarda cache a disco"""
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        self.cache_file.write_text(json.dumps(self._cache, ensure_ascii=False))
    
    async def get_price_at(self, timestamp: float) -> float | None:
        """Obtiene precio €/kWh para un timestamp específico"""
        dt = datetime.fromtimestamp(timestamp)
        key = dt.strftime("%Y-%m-%dT%H:00:00")
        
        # Verificar cache
        if key in self._cache["prices"]:
            return self._cache["prices"][key]
        
        # Si no está en cache, fetch del día completo
        await self._fetch_day_prices(dt)
        return self._cache["prices"].get(key)
    
    async def _fetch_day_prices(self, date: datetime):
        """Obtiene precios de un día completo"""
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
            for value in data["indicator"]["values"]:
                dt_str = value["datetime"][:16]  # "2026-06-22T00:00"
                price_mwh = value["value"]
                price_kwh = price_mwh / 1000  # MWh → kWh
                self._cache["prices"][dt_str] = price_kwh
            
            self._cache["last_fetch"] = datetime.now().timestamp()
            self._save_cache()
            logger.info(f"Precios PVPC actualizados para {start.date()}")
        
        except Exception as e:
            logger.error(f"Error obteniendo precios ESIOS: {e}")
```

### 3. Energy Tracker

**Archivo:** `src/backend/energy/tracker.py`

```python
import time
import json
from pathlib import Path
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

class EnergyTracker:
    """Seguimiento de consumo energético y coste"""
    
    def __init__(self, ac_controller, esios_client, data_dir: Path):
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
    
    def _load_json(self, path: Path, default: dict) -> dict:
        """Carga JSON desde disco"""
        if path.exists():
            try:
                return json.loads(path.read_text())
            except:
                pass
        return default
    
    def _save_json(self, path: Path, data: dict):
        """Guarda JSON a disco"""
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    
    def _recalculate_24h_totals(self):
        """Recalcula acumuladores 24h desde datos en disco"""
        self._current_24h_kwh = sum(h["kwh"] for h in self._hourly_data["data"].values())
        self._current_24h_cost = sum(h["cost"] for h in self._hourly_data["data"].values())
    
    async def record_hourly(self):
        """Registra consumo de la última hora (llamado cada :00)"""
        now = time.time()
        hour = datetime.fromtimestamp(now).strftime("%H")
        
        # Obtener consumo desde último registro
        kwh = self.ac.get_session_kwh()
        
        # Obtener precio de la hora anterior (hora en que se consumió)
        hour_ago = now - 3600
        price_per_kwh = await self.esios.get_price_at(hour_ago)
        if price_per_kwh is None:
            logger.warning("No se pudo obtener precio ESIOS, usando último conocido")
            price_per_kwh = self._get_last_known_price()
        
        cost = kwh * price_per_kwh
        
        # Remover hora que sale del rolling window (hace 24h)
        old_hour_data = self._hourly_data["data"].get(hour)
        if old_hour_data:
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
        
        logger.info(f"Registro horario: {kwh:.3f} kWh @ €{price_per_kwh:.5f}/kWh = €{cost:.3f}")
    
    async def record_daily(self):
        """Registra consumo del último día (llamado a las 00:00)"""
        now = time.time()
        date_key = datetime.fromtimestamp(now).strftime("%Y-%m-%d")
        
        # Sumar todas las horas del día anterior
        kwh_day = sum(h["kwh"] for h in self._hourly_data["data"].values())
        cost_day = sum(h["cost"] for h in self._hourly_data["data"].values())
        
        # Guardar en daily
        self._daily_data["data"][date_key] = {
            "kwh": round(kwh_day, 3),
            "cost": round(cost_day, 3),
            "timestamp": int(now)
        }
        self._daily_data["last_update"] = int(now)
        
        # Limitar a 365 días (rolling)
        if len(self._daily_data["data"]) > 365:
            # Eliminar el más antiguo
            oldest = min(self._daily_data["data"].keys())
            del self._daily_data["data"][oldest]
        
        self._save_json(self.daily_file, self._daily_data)
        
        logger.info(f"Registro diario {date_key}: {kwh_day:.3f} kWh = €{cost_day:.3f}")
    
    def get_current_24h(self) -> dict:
        """Devuelve totales de últimas 24h (desde acumuladores)"""
        return {
            "kwh": round(self._current_24h_kwh, 3),
            "cost": round(self._current_24h_cost, 2)
        }
    
    def get_hourly_stats(self) -> dict:
        """Devuelve datos para gráfica horaria"""
        return self._hourly_data["data"]
    
    def get_monthly_stats(self) -> dict:
        """Devuelve datos para gráfica mensual (agregado por mes)"""
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
        """Devuelve último precio conocido (fallback)"""
        if self._hourly_data["data"]:
            last_entry = list(self._hourly_data["data"].values())[-1]
            return last_entry.get("price_per_kwh", 0.15)
        return 0.15  # Fallback: 0.15 €/kWh (precio típico)
```

### 4. Integración en `main.py`

```python
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from energy.esios_client import ESIOSClient
from energy.tracker import EnergyTracker

# Variables globales
energy_tracker: EnergyTracker | None = None
scheduler: AsyncIOScheduler | None = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global energy_tracker, scheduler
    
    # ... código existente ...
    
    # 5. Inicializar cliente ESIOS
    esios_api_key = os.environ.get("ESIOS_API_KEY", "")
    data_dir = Path("/app/data")
    esios_client = ESIOSClient(esios_api_key, data_dir / "energy_prices_cache.json")
    
    # 6. Inicializar energy tracker
    energy_tracker = EnergyTracker(ac_controller, esios_client, data_dir)
    
    # 7. Inicializar scheduler
    scheduler = AsyncIOScheduler()
    
    # Job horario: cada hora en punto (:00)
    scheduler.add_job(
        energy_tracker.record_hourly,
        trigger='cron',
        minute=0,
        id='record_hourly'
    )
    
    # Job diario: cada día a las 00:00
    scheduler.add_job(
        energy_tracker.record_daily,
        trigger='cron',
        hour=0,
        minute=0,
        id='record_daily'
    )
    
    scheduler.start()
    logger.info("Scheduler de energía iniciado")
    
    # Inyectar en routes
    routes.energy_tracker = energy_tracker
    
    yield
    
    # Shutdown
    scheduler.shutdown()
```

### 5. Endpoints API

**Añadir en `src/backend/api/routes.py`:**

```python
energy_tracker = None  # Inyectado desde main.py

@router.get("/energy/current")
def get_energy_current():
    """Consumo y coste de últimas 24h"""
    totals = energy_tracker.get_current_24h()
    return {
        "kwh": totals["kwh"],
        "cost": totals["cost"],
        "last_update": time.time()
    }

@router.get("/energy/hourly")
def get_energy_hourly():
    """Datos para gráfica horaria (24h)"""
    return {"data": energy_tracker.get_hourly_stats()}

@router.get("/energy/monthly")
def get_energy_monthly():
    """Datos para gráfica mensual (12 meses)"""
    return {"data": energy_tracker.get_monthly_stats()}
```

### 6. Frontend - Widget

**Añadir en `index.html` (pantalla principal):**

```html
<!-- Después del widget de humedad -->
<div class="card" onclick="openEnergyPopup()">
    <div class="label">ENERGÍA (24h)</div>
    <div class="value">
        <span id="energy-kwh">--</span> kWh
    </div>
    <div class="text-xs text-slate-400 mt-1">
        €<span id="energy-cost">--</span>
    </div>
</div>
```

**JavaScript para actualizar widget:**

```javascript
async function updateEnergyWidget() {
    try {
        const resp = await fetch('/api/energy/current');
        const data = await resp.json();
        document.getElementById('energy-kwh').textContent = data.kwh.toFixed(2);
        document.getElementById('energy-cost').textContent = data.cost.toFixed(2);
    } catch (e) {
        console.error('Error energy widget:', e);
    }
}

// Llamar cada minuto
setInterval(updateEnergyWidget, 60000);
updateEnergyWidget();  // Inicial
```

### 7. Frontend - Popup

**Añadir en `index.html`:**

```html
<!-- Popup de estadísticas energéticas -->
<div id="energy-popup" class="popup" style="display:none">
    <div class="popup-header">
        <h2>Consumo Energético</h2>
        <button onclick="closeEnergyPopup()">×</button>
    </div>
    
    <div class="energy-summary">
        <div class="stat">
            <span class="label">Últimas 24h:</span>
            <span class="value"><span id="summary-24h-kwh">--</span> kWh (€<span id="summary-24h-cost">--</span>)</span>
        </div>
    </div>
    
    <div class="chart-section">
        <h3>Consumo por Horas</h3>
        <canvas id="energy-hourly-chart"></canvas>
    </div>
    
    <div class="chart-section">
        <h3>Consumo por Mes</h3>
        <canvas id="energy-monthly-chart"></canvas>
    </div>
</div>

<script>
let energyHourlyChart, energyMonthlyChart;

function openEnergyPopup() {
    document.getElementById('energy-popup').style.display = 'flex';
    loadEnergyStats();
}

function closeEnergyPopup() {
    document.getElementById('energy-popup').style.display = 'none';
}

async function loadEnergyStats() {
    // Cargar datos
    const [hourly, monthly, current] = await Promise.all([
        fetch('/api/energy/hourly').then(r => r.json()),
        fetch('/api/energy/monthly').then(r => r.json()),
        fetch('/api/energy/current').then(r => r.json())
    ]);
    
    // Actualizar resumen
    document.getElementById('summary-24h-kwh').textContent = current.kwh.toFixed(2);
    document.getElementById('summary-24h-cost').textContent = current.cost.toFixed(2);
    
    // Gráfica horaria
    updateEnergyHourlyChart(hourly.data);
    
    // Gráfica mensual
    updateEnergyMonthlyChart(monthly.data);
}

function updateEnergyHourlyChart(data) {
    const hours = Object.keys(data).sort();
    const kwh = hours.map(h => data[h].kwh);
    const cost = hours.map(h => data[h].cost);
    
    const ctx = document.getElementById('energy-hourly-chart').getContext('2d');
    
    if (energyHourlyChart) energyHourlyChart.destroy();
    
    energyHourlyChart = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: hours.map(h => h + ':00'),
            datasets: [
                {
                    label: 'kWh',
                    data: kwh,
                    backgroundColor: 'rgba(59, 130, 246, 0.7)',
                    yAxisID: 'y'
                },
                {
                    label: 'Coste €',
                    data: cost,
                    type: 'line',
                    borderColor: '#10b981',
                    backgroundColor: 'rgba(16, 185, 129, 0.1)',
                    yAxisID: 'y1'
                }
            ]
        },
        options: {
            responsive: true,
            scales: {
                y: {
                    type: 'linear',
                    position: 'left',
                    title: { display: true, text: 'kWh' }
                },
                y1: {
                    type: 'linear',
                    position: 'right',
                    title: { display: true, text: '€' },
                    grid: { drawOnChartArea: false }
                }
            }
        }
    });
}

function updateEnergyMonthlyChart(data) {
    const months = Object.keys(data).sort();
    const kwh = months.map(m => data[m].kwh);
    const cost = months.map(m => data[m].cost);
    
    const ctx = document.getElementById('energy-monthly-chart').getContext('2d');
    
    if (energyMonthlyChart) energyMonthlyChart.destroy();
    
    energyMonthlyChart = new Chart(ctx, {
        type: 'bar',
        data: {
            labels: months.map(m => m.slice(5)),  // "06" de "2026-06"
            datasets: [
                {
                    label: 'kWh',
                    data: kwh,
                    backgroundColor: 'rgba(139, 92, 246, 0.7)',
                    yAxisID: 'y'
                },
                {
                    label: 'Coste €',
                    data: cost,
                    type: 'line',
                    borderColor: '#f59e0b',
                    backgroundColor: 'rgba(245, 158, 11, 0.1)',
                    yAxisID: 'y1'
                }
            ]
        },
        options: {
            responsive: true,
            scales: {
                y: {
                    type: 'linear',
                    position: 'left',
                    title: { display: true, text: 'kWh' }
                },
                y1: {
                    type: 'linear',
                    position: 'right',
                    title: { display: true, text: '€' },
                    grid: { drawOnChartArea: false }
                }
            }
        }
    });
}
</script>
```

---

## 📦 Dependencias

**Añadir a `requirements.txt`:**
```
apscheduler==3.10.4
```

---

## 🔐 Variables de Entorno

**Añadir a `.env`:**
```
ESIOS_API_KEY=your_api_key_here
```

**Obtener API Key:**
1. Registrarse en https://www.esios.ree.es/es/pagina/api
2. Solicitar API Key (gratuita)
3. Añadir al `.env`

---

## ✅ Criterios de Aceptación

- [ ] Widget "ENERGÍA (24h)" visible en pantalla principal
- [ ] Widget muestra kWh y coste en € actualizados cada minuto
- [ ] Click en widget abre popup con estadísticas
- [ ] Popup muestra 2 gráficas: horaria (24h) y mensual (12 meses)
- [ ] Gráfica horaria: barras kWh + línea coste €
- [ ] Gráfica mensual: barras kWh + línea coste €
- [ ] Scheduler registra consumo cada hora (:00)
- [ ] Scheduler registra consumo cada día (00:00)
- [ ] JSON `energy_hourly.json` contiene 24 registros
- [ ] JSON `energy_daily.json` contiene hasta 365 registros
- [ ] Precios obtenidos de API ESIOS
- [ ] Coste calculado con precio exacto del momento
- [ ] Sistema eficiente (acumuladores en memoria)
- [ ] Persiste correctamente tras reinicio

---

**Estado:** DISEÑO COMPLETO  
**Próximo paso:** IMPLEMENTACIÓN

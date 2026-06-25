# Frontend Refactoring Plan - Modular Architecture

## Problema Actual

**index.html: 1033 líneas monolíticas**
- HTML + CSS + JavaScript todo mezclado
- Difícil de mantener y extender
- Imposible de testear unitariamente
- Alto riesgo de introducir bugs al modificar

## Requisito F0.29

**Sistema modular, archivos pequeños y expandibles**

Archivos de código deben ser:
- ✅ Modulares (separación de responsabilidades)
- ✅ Pequeños (máx 200-300 líneas por archivo)
- ✅ Fáciles de modificar
- ✅ Fáciles de expandir

## Estrategia de Refactorización

### Fase 1: Análisis y Preparación (1 hora)
- [ ] Mapear todas las funciones en index.html
- [ ] Identificar dependencias entre funciones
- [ ] Crear estructura de carpetas
- [ ] Configurar sistema de módulos ES6

### Fase 2: Extraer Utilidades (1 hora)
**Objetivo:** Funciones sin dependencias del DOM

Archivos a crear:
- js/utils/formatters.js (~50 líneas)
  - formatTemperature()
  - formatHumidity()
  - formatTimestamp()
  - formatDuration()

- js/utils/colorUtils.js (~80 líneas)
  - getTempColor()
  - getHumidityColor()
  - getTempBgColor()
  - getHumidityBgColor()
  - All color range logic

- js/utils/domHelpers.js (~60 líneas)
  - createElement()
  - updateElement()
  - showElement()
  - hideElement()

### Fase 3: Extraer Servicios (1.5 horas)
**Objetivo:** Lógica de negocio y comunicación

Archivos a crear:
- js/services/apiClient.js (~150 líneas)
  - fetchData()
  - fetchSensorHistory()
  - updateTargetTemp()
  - setManualMode()
  - All API endpoints

- js/services/stateManager.js (~100 líneas)
  - AppState class
  - state getters/setters
  - state persistence
  - state observers

- js/services/websocketClient.js (~80 líneas)
  - WebSocket connection
  - Real-time updates
  - Reconnection logic

### Fase 4: Extraer Componentes UI (2 horas)
**Objetivo:** Componentes visuales reutilizables

Archivos a crear:
- js/components/temperatureCard.js (~120 líneas)
  - TemperatureCard class
  - render()
  - update()
  - Event handlers

- js/components/humidityCard.js (~100 líneas)
  - HumidityCard class
  - Similar to TemperatureCard

- js/components/controlPanel.js (~150 líneas)
  - ControlPanel class
  - Target temperature slider
  - Mode buttons
  - Manual controls

- js/components/modeSelector.js (~80 líneas)
  - ModeSelector class
  - Auto/Manual/OFF buttons
  - State management

- js/components/chartManager.js (~200 líneas)
  - ChartManager class
  - Initialize Chart.js
  - Update charts
  - Handle data

- js/components/languageSelector.js (~60 líneas)
  - LanguageSelector class
  - Dropdown
  - i18n integration

### Fase 5: Main App (30 min)
**Objetivo:** Orquestar todos los módulos

- js/main.js (~150 líneas)
  - App initialization
  - Component instantiation
  - Event loop
  - Update cycle

### Fase 6: Limpiar HTML (30 min)
**Objetivo:** HTML mínimo, solo estructura

- index.html (~150 líneas)
  - Solo HTML semántico
  - Links a CSS
  - Module imports
  - Sin JavaScript inline

## Estructura Final

\\\
src/backend/static/
├── index.html                      # 150 líneas (vs 1033)
├── css/
│   └── main.css                    # Extracted from inline
├── js/
│   ├── main.js                     # 150 líneas - Entry point
│   ├── components/
│   │   ├── temperatureCard.js      # 120 líneas
│   │   ├── humidityCard.js         # 100 líneas
│   │   ├── controlPanel.js         # 150 líneas
│   │   ├── modeSelector.js         # 80 líneas
│   │   ├── chartManager.js         # 200 líneas
│   │   └── languageSelector.js     # 60 líneas
│   ├── services/
│   │   ├── apiClient.js            # 150 líneas
│   │   ├── stateManager.js         # 100 líneas
│   │   └── websocketClient.js      # 80 líneas
│   ├── utils/
│   │   ├── formatters.js           # 50 líneas
│   │   ├── colorUtils.js           # 80 líneas
│   │   └── domHelpers.js           # 60 líneas
│   └── i18n.js                     # Ya existe
├── locales/                        # Ya existe
└── flags/                          # Ya existe

Total: ~1480 líneas organizadas en 15 archivos modulares
       (vs 1033 líneas en 1 archivo monolítico)
\\\

## Reglas de Implementación

### 1. Un archivo, una responsabilidad
- Cada archivo debe tener un propósito claro
- Nombres descriptivos
- Exports explícitos

### 2. Máximo 300 líneas por archivo
- Si supera, dividir en sub-módulos
- Priorizar legibilidad sobre cantidad de archivos

### 3. ES6 Modules
\\\javascript
// Export
export class TemperatureCard { ... }
export function formatTemperature(temp) { ... }

// Import
import { TemperatureCard } from './components/temperatureCard.js';
import { formatTemperature } from './utils/formatters.js';
\\\

### 4. Sin dependencias circulares
- Utils no dependen de nadie
- Services dependen solo de utils
- Components dependen de services y utils
- Main depende de components

### 5. Testing en mente
- Funciones puras donde sea posible
- Dependency injection
- Mock-friendly

## Checklist de Testing Post-Refactor

- [ ] UI se ve igual que antes
- [ ] Temperatura se actualiza correctamente
- [ ] Humedad se actualiza correctamente
- [ ] Gráficas funcionan
- [ ] Control manual funciona
- [ ] Cambio de modo funciona
- [ ] Cambio de idioma funciona
- [ ] Todos los sensores se muestran
- [ ] Colores son correctos
- [ ] Responsive funciona
- [ ] Sin errores en consola
- [ ] Performance similar o mejor

## Riesgos y Mitigaciones

| Riesgo | Probabilidad | Impacto | Mitigación |
|--------|--------------|---------|------------|
| Romper funcionalidad existente | Media | Alto | Testing exhaustivo, git branch |
| Problemas de carga de módulos | Baja | Medio | Servidor debe servir con MIME correcto |
| Performance degradada | Baja | Medio | Bundling opcional si necesario |
| Browser compatibility | Baja | Bajo | ES6 modules ya se usan (i18n.js) |

## Cronograma Estimado

- **Total:** 6 horas
- **Puede hacerse en:** 2-3 sesiones
- **Recomendación:** Hacer en una sola sesión para mantener contexto

## Valor Esperado

### Antes del Refactor
- ❌ 1033 líneas en un archivo
- ❌ Difícil añadir features
- ❌ Alto riesgo de bugs
- ❌ Imposible testear
- ❌ Difícil onboarding

### Después del Refactor
- ✅ 15 archivos modulares
- ✅ Fácil añadir features
- ✅ Bajo riesgo de bugs
- ✅ Testeable
- ✅ Fácil onboarding
- ✅ Código mantenible
- ✅ Preparado para escalar

---

**Prioridad:** HIGH (bloquea desarrollo escalable)  
**Esfuerzo:** 6 horas  
**ROI:** Muy alto (desbloquea velocidad futura)  
**Cuándo hacerlo:** Antes de añadir más features

**Creado:** 24 Junio 2026  
**Estado:** Planeado, esperando implementación

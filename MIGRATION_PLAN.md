# Plan de Migración: CI/CD con GitHub Actions

## Resumen Ejecutivo

**Objetivo**: Implementar un flujo CI/CD profesional usando GitHub Actions que:
1. Ejecute tests automáticamente en cada push
2. Permita deploy manual a Raspberry Pi (desde GitHub UI o desde Kiro)
3. Use Docker images pre-built para optimizar espacio en Pi
4. Reestructure el proyecto por servicios para mejor organización
5. Excluya archivos de steering del repositorio GitHub

**Estado**: 🚧 EN PROGRESO (Fases 0-4 completadas, Fase 5 en curso)

---

## Arquitectura Actual (investigada)

### ⚠️ DATOS CRÍTICOS - IMMICH (NO TOCAR)

**Immich es un servicio INDEPENDIENTE** que gestiona las fotos de la familia. Sus datos están en discos duros externos y **NO forman parte de esta migración**.

#### Ubicación de datos de Immich

| Ruta | Disco | Tamaño | Contenido |
|------|-------|--------|-----------|
| `/mnt/immich` | HDD externo 1.8TB | ~1.8TB | Fotos y vídeos originales |
| `/mnt/immich-backup` | HDD externo 458GB | ~458GB | Backup de Immich |

#### Configuración de Immich (referencia)

```
Proyecto: ~/projects/immich/
docker-compose.yml: Usa volúmenes montados en /mnt/immich
```

**¿Por qué Immich NO se toca en esta migración?**
1. Es un proyecto completamente separado (`~/projects/immich/`)
2. Sus datos están en discos duros externos montados, no en `~/projects/smart-home/`
3. No tiene relación con el código de smart-home
4. Seguirá funcionando con su docker-compose propio

**Verificación antes de la migración:**
```bash
# Confirmar que los discos están montados correctamente
df -h | grep immich
# Debería mostrar:
# /dev/sda1  1.8T  xxxG  xxxG  xx% /mnt/immich
# /dev/sdb1  458G  xxxG  xxxG  xx% /mnt/immich-backup

# Confirmar que Immich está corriendo
docker ps | grep immich
```

**REGLA: Durante la Fase 6, NUNCA ejecutar comandos que afecten a:**
- `/mnt/immich`
- `/mnt/immich-backup`
- `~/projects/immich/`

---

### Estructura de datos en la Pi (smart-home)

```
~/projects/smart-home/data/          # DATOS PERSISTENTES (CRÍTICO - NO BORRAR)
├── backend/
│   ├── auth.db                      # Base de datos de autenticación
│   ├── controller_state.json        # Estado del controlador AC
│   ├── humidity_analysis.json
│   ├── humidity_hourly.json
│   ├── outdoor_reading.json
│   ├── sensor_readings.json
│   └── vacaciones.json
├── baby-gifts-service/
│   ├── baby_gifts.db                # SQLite con invitaciones
│   └── gifts.json                   # 🎁 Lista de regalos (Virchu puede estar editando)
├── ac-service/
│   ├── controller_state.json
│   ├── humidity_analysis.json
│   ├── humidity_hourly.json
│   └── sensor_readings.json
├── vacaciones-service/
│   └── vacaciones.json
├── casita-suenos/
│   ├── casita.db                    # SQLite con pisos
│   ├── gmail_token.json             # OAuth tokens
│   ├── gmail_credentials.json
│   └── apify_usage.json
├── zigbee2mqtt/
│   ├── state.json
│   ├── coordinator_backup.json
│   └── database.db
├── mosquitto/
│   ├── data/mosquitto.db
│   └── log/
├── nginx/logs/
└── vaultwarden/                     # Servicio independiente
```

### Servicios corriendo actualmente

| Servicio | Imagen/Build | Puerto | docker-compose |
|----------|--------------|--------|----------------|
| smart-home-backend | build local | 8080 | ~/projects/smart-home/ |
| baby-gifts-service | build local | 8004 | ~/projects/smart-home/ |
| ac-service | build local | 8002 | ~/projects/ac-service/ |
| vacaciones-service | build local | 8003 | ~/projects/vacaciones-service/ |
| casita-suenos | build local | 8001 | ~/projects/casita-suenos/ |
| nginx-reverse-proxy | nginx:alpine | 80,443 | ~/projects/smart-home/ |
| mosquitto | eclipse-mosquitto:2 | 1883 | ~/projects/smart-home/ |
| zigbee2mqtt | koenkk/zigbee2mqtt | 8081 | ~/projects/smart-home/ |
| docker-socket-proxy | tecnativa/docker-socket-proxy | 2375 | ~/projects/smart-home/ |
| vaultwarden | vaultwarden/server | - | ~/projects/vaultwarden/ |
| immich_server | immich-server | - | ~/projects/immich/ |
| valheim-admin | valheim-admin | - | ~/projects/valheim-server/ |

### Archivos .env necesarios

```
~/projects/smart-home/.env           # MELCloud, AUTH_SECRET, SMTP
~/projects/ac-service/.env           # MELCloud (copia)
~/projects/casita-suenos/.env        # MELCloud, Apify, Telegram, Gmail, AUTH
```

**Variables críticas**:
- `MELCLOUD_EMAIL`, `MELCLOUD_PASSWORD`, `MELCLOUD_DEVICE_ID`, `MELCLOUD_BUILDING_ID`
- `AUTH_SECRET` (JWT)
- `AUTH_SMTP_USER`, `AUTH_SMTP_PASSWORD`
- `APIFY_API_TOKEN`
- `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`
- `GMAIL_ADDRESS`, `GMAIL_APP_PASSWORD`
- `FIRMS_MAP_KEY`

---

## Fases del Proyecto

### Fase 0: Preparación y Backup
**Estado**: ✅ COMPLETADA
**Duración estimada**: 30 min

- [x] 0.1 Crear backup completo del estado actual
  - Commit de todo el código actual
  - Tag de versión `pre-migration-v1` ✅
  - Push a GitHub como respaldo ✅
  
- [x] 0.2 Documentar estructura actual
  - ✅ Ya documentado arriba
  
- [x] 0.3 Verificar acceso a servicios externos
  - Docker Hub: usuario `egnal` ✅
  - GitHub Actions habilitado ✅
  - GitHub CLI (`gh`) instalado y autenticado (HTTPS) ✅

---

### Fase 1: Reestructuración de Carpetas
**Estado**: ✅ COMPLETADA (commit 9ec70e9)
**Duración estimada**: 2-3 horas
**Dependencias**: Fase 0 completada

#### 1.1 Estructura final esperada

```
smart-home/
├── .github/
│   └── workflows/
│       ├── test.yml
│       └── deploy.yml
├── dashboard/                        # 🎯 NÚCLEO CENTRAL
│   ├── src/
│   │   ├── api/
│   │   ├── controllers/
│   │   ├── static/                   # Frontend HTML/JS/CSS
│   │   ├── main.py
│   │   ├── auth.py
│   │   └── ... (resto de módulos)
│   ├── tests/
│   │   ├── unit/
│   │   ├── integration/
│   │   └── conftest.py
│   ├── Dockerfile
│   ├── requirements.txt
│   └── README.md
├── services/                         # 📦 MICROSERVICIOS
│   ├── ac-service/
│   │   ├── src/
│   │   ├── tests/
│   │   ├── Dockerfile
│   │   └── requirements.txt
│   ├── baby-gifts-service/
│   │   ├── src/
│   │   ├── tests/
│   │   ├── Dockerfile
│   │   └── requirements.txt
│   ├── vacaciones-service/
│   │   ├── src/
│   │   ├── tests/
│   │   ├── Dockerfile
│   │   └── requirements.txt
│   └── casita-suenos/
│       ├── src/
│       ├── tests/
│       ├── Dockerfile
│       └── requirements.txt
├── infrastructure/                   # 🔧 INFRAESTRUCTURA
│   ├── nginx/
│   │   ├── nginx.conf
│   │   ├── conf.d/
│   │   ├── .htpasswd
│   │   └── certs/
│   └── mosquitto/
│       └── mosquitto.conf
├── scripts/
├── tools/
├── docker-compose.yml                # Desarrollo local (usa build:)
├── docker-compose.prod.yml           # Producción Pi (usa image:)
├── .env.example
├── pytest.ini
├── README.md
└── ... (otros archivos raíz)
```

**NOTA**: La carpeta `.kiro/` NO se sube a GitHub (añadida a `.gitignore`)

#### 1.2 Mapeo de migración

| Origen | Destino |
|--------|---------|
| `src/backend/*` | `dashboard/src/` |
| `src/backend/Dockerfile` | `dashboard/Dockerfile` |
| `src/backend/requirements.txt` | `dashboard/requirements.txt` |
| `tests/unit/` | `dashboard/tests/unit/` |
| `tests/integration/` | `dashboard/tests/integration/` |
| `tests/conftest.py` | `dashboard/tests/conftest.py` |
| `ac-service/` | `services/ac-service/` |
| `baby-gifts-service/` | `services/baby-gifts-service/` |
| `vacaciones-service/` | `services/vacaciones-service/` |
| `casita-suenos/` | `services/casita-suenos/` |

#### 1.3 Actualizar referencias
- [ ] docker-compose.yml - actualizar paths de build context
- [ ] Eliminar docker-compose individuales de servicios (consolidar en uno)
- [ ] Actualizar nginx.conf si hay paths hardcodeados

#### 1.4 Actualizar .gitignore
```gitignore
# Añadir al .gitignore
.kiro/
*.steering.md
```

#### 1.5 Verificación local
- [ ] `docker-compose build` funciona
- [ ] `docker-compose up` levanta todos los servicios
- [ ] Tests locales pasan

---

### Fase 2: Optimización de Dockerfiles
**Estado**: ✅ COMPLETADA (commit b7464d2)
**Duración estimada**: 1-2 horas
**Dependencias**: Fase 1 completada

#### 2.1 Crear Dockerfiles multi-stage

```dockerfile
# Plantilla para servicios Python
FROM python:3.11-slim as builder
WORKDIR /build
COPY requirements.txt .
RUN pip install --user --no-cache-dir -r requirements.txt

FROM python:3.11-slim
WORKDIR /app
COPY --from=builder /root/.local /root/.local
COPY src/ ./src/
ENV PATH=/root/.local/bin:$PATH
EXPOSE 800X
CMD ["python", "src/main.py"]
```

#### 2.2 Crear .dockerignore para cada servicio
```
tests/
*.pyc
__pycache__/
.git/
.env
*.md
.pytest_cache/
.kiro/
```

#### 2.3 Verificar tamaño de imágenes
- Objetivo: < 150MB por servicio

---

### Fase 3: Configuración de Docker Hub
**Estado**: ✅ COMPLETADA
**Duración estimada**: 30 min
**Dependencias**: Fase 2 completada

#### 3.1 Repositorios creados (automáticamente al hacer push)
- [x] `egnal/smart-home-baby-gifts` (199MB - test exitoso)
- [ ] Resto se crearán al deployar cada servicio

#### 3.2 Test manual de push ✅
```bash
# Probado con baby-gifts-service
docker build -t egnal/smart-home-baby-gifts:latest ./services/baby-gifts-service
docker push egnal/smart-home-baby-gifts:latest
# Resultado: 199MB imagen subida correctamente
```

---

### Fase 4: GitHub Actions - Tests Automáticos
**Estado**: ✅ COMPLETADA (commit e6e0881)
**Duración estimada**: 1-2 horas
**Dependencias**: Fase 1 completada

> **Nota**: El workflow se ejecuta pero algunos tests de integración fallan por paths hardcodeados antiguos (`src/backend/static`). Esto se arreglará más adelante, no bloquea la migración.

#### 4.1 Crear .github/workflows/test.yml

```yaml
name: Tests
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  detect-changes:
    runs-on: ubuntu-latest
    outputs:
      dashboard: ${{ steps.filter.outputs.dashboard }}
      ac-service: ${{ steps.filter.outputs.ac-service }}
      baby-gifts: ${{ steps.filter.outputs.baby-gifts }}
      vacaciones: ${{ steps.filter.outputs.vacaciones }}
      casita: ${{ steps.filter.outputs.casita }}
    steps:
      - uses: actions/checkout@v4
      - uses: dorny/paths-filter@v2
        id: filter
        with:
          filters: |
            dashboard:
              - 'dashboard/**'
            ac-service:
              - 'services/ac-service/**'
            baby-gifts:
              - 'services/baby-gifts-service/**'
            vacaciones:
              - 'services/vacaciones-service/**'
            casita:
              - 'services/casita-suenos/**'

  test-dashboard:
    needs: detect-changes
    if: ${{ needs.detect-changes.outputs.dashboard == 'true' }}
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
      - run: pip install -r dashboard/requirements.txt pytest
      - run: pytest dashboard/tests/

  # ... similar para otros servicios

  notify-failure:
    needs: [test-dashboard]
    if: failure()
    runs-on: ubuntu-latest
    steps:
      - name: Send notification
        run: echo "Tests failed - notification would be sent here"
```

#### 4.2 Verificación
- [ ] Push de prueba dispara tests
- [ ] Solo se ejecutan tests de servicios modificados

---

### Fase 5: GitHub Actions - Deploy Manual
**Estado**: 🚧 EN CURSO (workflows creados, secrets configurados, pendiente test)
**Duración estimada**: 2-3 horas
**Dependencias**: Fases 3 y 4 completadas

#### 5.1 Configurar secrets en GitHub ✅

| Secret | Valor | Estado |
|--------|-------|--------|
| `DOCKERHUB_TOKEN` | Token de acceso Docker Hub | ✅ Configurado |
| `PI_SSH_HOST` | raspberrypi.local | ✅ Configurado |
| `PI_SSH_USER` | pi | ✅ Configurado |
| `PI_SSH_KEY` | Clave privada SSH | ✅ Configurado |

> **Nota**: Se usa `DOCKERHUB_TOKEN` en lugar de `DOCKERHUB_USERNAME` + token separados. El username `egnal` está hardcodeado en el workflow.

#### 5.2 Crear .github/workflows/deploy.yml

```yaml
name: Deploy to Raspberry Pi
on:
  workflow_dispatch:
    inputs:
      service:
        description: 'Servicio a deployar'
        required: true
        type: choice
        options:
          - all
          - dashboard
          - ac-service
          - baby-gifts-service
          - vacaciones-service
          - casita-suenos

jobs:
  build-and-push:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: docker/setup-buildx-action@v3
      - uses: docker/login-action@v3
        with:
          username: ${{ secrets.DOCKERHUB_USERNAME }}
          password: ${{ secrets.DOCKERHUB_TOKEN }}
      - name: Build and push
        run: |
          # Build según el servicio seleccionado
          # Push a Docker Hub con tag :latest y :${{ github.sha }}

  deploy:
    needs: build-and-push
    runs-on: ubuntu-latest
    steps:
      - name: SSH and deploy
        uses: appleboy/ssh-action@v1
        with:
          host: ${{ secrets.PI_SSH_HOST }}
          username: ${{ secrets.PI_SSH_USER }}
          key: ${{ secrets.PI_SSH_KEY }}
          script: |
            cd ~/smart-home-prod
            docker-compose pull ${{ github.event.inputs.service }}
            docker-compose up -d ${{ github.event.inputs.service }}
```

#### 5.3 Crear hook de Kiro para deploy desde chat

**Ubicación**: `.kiro/hooks/deploy-service.json`

```json
{
  "version": "v1",
  "hooks": [{
    "name": "Deploy Service",
    "trigger": "UserPromptSubmit",
    "matcher": "^deploy\\s+",
    "action": {
      "type": "agent",
      "prompt": "El usuario quiere deployar un servicio a la Raspberry Pi. Ejecuta: gh workflow run deploy.yml -f service=<nombre>. Servicios: all, dashboard, ac-service, baby-gifts-service, vacaciones-service, casita-suenos. Confirma el resultado del comando."
    }
  }]
}
```

#### 5.4 Crear docker-compose.prod.yml para la Pi

```yaml
# docker-compose.prod.yml - Para producción en Raspberry Pi
# Solo usa imágenes de Docker Hub, no builds locales

services:
  mosquitto:
    image: eclipse-mosquitto:2
    container_name: mosquitto
    restart: unless-stopped
    volumes:
      - ./infrastructure/mosquitto/mosquitto.conf:/mosquitto/config/mosquitto.conf
      - ./data/mosquitto/data:/mosquitto/data
      - ./data/mosquitto/log:/mosquitto/log
    networks:
      - smart-home

  zigbee2mqtt:
    image: koenkk/zigbee2mqtt:latest
    container_name: zigbee2mqtt
    restart: unless-stopped
    depends_on:
      - mosquitto
    volumes:
      - ./data/zigbee2mqtt:/app/data
      - /run/udev:/run/udev:ro
    devices:
      - /dev/ttyUSB0:/dev/ttyUSB0
    environment:
      - TZ=Europe/Madrid
    networks:
      - smart-home

  dashboard:
    image: egnal/smart-home-dashboard:latest
    container_name: smart-home-backend
    restart: unless-stopped
    volumes:
      - ./data/backend:/app/data
      - ./infrastructure/nginx/.htpasswd:/etc/nginx/.htpasswd:ro
    env_file:
      - .env
    environment:
      - TZ=Europe/Madrid
    networks:
      - smart-home

  ac-service:
    image: egnal/smart-home-ac-service:latest
    container_name: ac-service
    restart: unless-stopped
    volumes:
      - ./data/ac-service:/app/data
    env_file:
      - .env
    environment:
      - TZ=Europe/Madrid
      - MQTT_BROKER=mosquitto
    networks:
      - smart-home

  baby-gifts-service:
    image: egnal/smart-home-baby-gifts:latest
    container_name: baby-gifts-service
    restart: unless-stopped
    volumes:
      - ./data/baby-gifts-service:/app/data
    environment:
      - TZ=Europe/Madrid
    networks:
      - smart-home

  vacaciones-service:
    image: egnal/smart-home-vacaciones:latest
    container_name: vacaciones-service
    restart: unless-stopped
    volumes:
      - ./data/vacaciones-service:/app/data
    environment:
      - TZ=Europe/Madrid
    networks:
      - smart-home

  casita-suenos:
    image: egnal/smart-home-casita-suenos:latest
    container_name: casita-suenos
    restart: unless-stopped
    volumes:
      - ./data/casita-suenos:/app/data
    env_file:
      - .env
    environment:
      - TZ=Europe/Madrid
    networks:
      - smart-home

  nginx:
    image: nginx:alpine
    container_name: nginx-reverse-proxy
    restart: unless-stopped
    depends_on:
      - dashboard
      - zigbee2mqtt
    ports:
      - 80:80
      - 8443:443
    volumes:
      - ./infrastructure/nginx/nginx.conf:/etc/nginx/nginx.conf:ro
      - ./infrastructure/nginx/conf.d:/etc/nginx/conf.d:ro
      - ./infrastructure/nginx/.htpasswd:/etc/nginx/.htpasswd:ro
      - ./infrastructure/nginx/certs:/etc/nginx/certs:ro
      - ./data/nginx/logs:/var/log/nginx
    networks:
      - smart-home

  docker-socket-proxy:
    image: ghcr.io/tecnativa/docker-socket-proxy:latest
    container_name: docker-socket-proxy
    restart: unless-stopped
    environment:
      CONTAINERS: 1
      POST: 1
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
    networks:
      - smart-home

networks:
  smart-home:
    driver: bridge
```

---

### Fase 6: Deploy Pi - Backup → Cleanup → Deploy (en este orden exacto)
**Estado**: ⬜ Pendiente
**Duración estimada**: 2-3 horas
**Dependencias**: Fase 5 completada

#### ⚠️ RECORDATORIO: DATOS QUE NO SE TOCAN

| Servicio | Ubicación | Acción |
|----------|-----------|--------|
| **Immich** | `/mnt/immich`, `/mnt/immich-backup`, `~/projects/immich/` | ❌ NO TOCAR - disco externo independiente |
| **Vaultwarden** | `~/projects/vaultwarden/` | ❌ NO TOCAR - servicio independiente |
| **Valheim** | `~/projects/valheim-server/` | ❌ NO TOCAR - servicio independiente |

Estos servicios tienen sus propios docker-compose y seguirán funcionando sin cambios.

#### 6.1 ⚠️ BACKUP DATOS CRÍTICOS

**ANTES DE CUALQUIER CAMBIO**, respaldar datos que Virchu puede estar editando:

```bash
# En la Pi - Ejecutar PRIMERO
ssh pi@raspberrypi.local

# 1. Backup del JSON de regalos (CRÍTICO)
cp ~/projects/smart-home/data/baby-gifts-service/gifts.json ~/backup_gifts_$(date +%Y%m%d_%H%M%S).json
cp ~/projects/smart-home/data/baby-gifts-service/baby_gifts.db ~/backup_baby_gifts_$(date +%Y%m%d_%H%M%S).db

# 2. Backup de TODA la carpeta data
tar -czvf ~/backup_data_$(date +%Y%m%d_%H%M%S).tar.gz ~/projects/smart-home/data/

# 3. Backup de archivos .env
cp ~/projects/smart-home/.env ~/backup_env_smart_home.env
cp ~/projects/ac-service/.env ~/backup_env_ac_service.env
cp ~/projects/casita-suenos/.env ~/backup_env_casita_suenos.env

# 4. Subir gifts.json actualizado al repo (por si Virchu hizo cambios)
# Esto se hace desde Windows después de copiar el archivo
```

**Verificar contenido del backup de gifts.json**:
El archivo contiene:
- Lista completa de regalos con: id, name, description, url, price_range, category, priority
- Estado de reservas: reserved_by, reserved_by_name, reserved_at
- Categorías disponibles

#### 6.2 Subir última versión de datos al repo

```powershell
# En Windows
scp pi@raspberrypi.local:~/projects/smart-home/data/baby-gifts-service/gifts.json C:\Users\acmls\Documents\Development\smart-home\services\baby-gifts-service\data\gifts.json
git add services/baby-gifts-service/data/gifts.json
git commit -m "chore: backup gifts.json before migration"
git push origin main
```

#### 6.3 Cleanup de la Raspberry Pi

```bash
# ⚠️ IMPORTANTE: Solo borrar proyectos de smart-home
# NO TOCAR: ~/projects/immich, ~/projects/vaultwarden, ~/projects/valheim-server

# 1. Parar SOLO los contenedores de smart-home
cd ~/projects/smart-home
docker-compose down
cd ~/projects/ac-service && docker-compose down
cd ~/projects/vacaciones-service && docker-compose down
cd ~/projects/casita-suenos && docker-compose down

# 2. Crear nueva estructura de producción
mkdir -p ~/smart-home-prod
cd ~/smart-home-prod

# 3. Copiar archivos necesarios
mkdir -p data infrastructure

# Copiar datos persistentes
cp -r ~/projects/smart-home/data/* ./data/

# Copiar configuración de infraestructura
cp -r ~/projects/smart-home/infrastructure/nginx ./infrastructure/
cp -r ~/projects/smart-home/infrastructure/mosquitto ./infrastructure/

# Copiar .env consolidado
cp ~/projects/smart-home/.env ./.env

# 4. Copiar docker-compose.prod.yml (se habrá deployado desde GitHub)
# O crearlo manualmente basándose en el template de arriba

# 5. Eliminar código fuente antiguo DE SMART-HOME SOLAMENTE
# ⚠️ VERIFICAR que son las carpetas correctas antes de ejecutar
rm -rf ~/projects/smart-home
rm -rf ~/projects/ac-service
rm -rf ~/projects/vacaciones-service
rm -rf ~/projects/casita-suenos
rm -rf ~/repos/smart-home.git

# ❌ NO EJECUTAR - Estos proyectos son independientes:
# rm -rf ~/projects/immich        # ¡NO! Fotos en disco externo
# rm -rf ~/projects/vaultwarden   # ¡NO! Contraseñas
# rm -rf ~/projects/valheim-server # ¡NO! Servidor de juego

# 6. Limpiar Docker (solo imágenes no usadas, no volúmenes de otros servicios)
docker image prune -a -f
# NO usar: docker system prune -a --volumes -f (borraría volúmenes de Immich)
```

#### 6.4 Deploy inicial desde imágenes

```bash
cd ~/smart-home-prod

# Pull de todas las imágenes
docker-compose pull

# Levantar servicios
docker-compose up -d

# Verificar
docker ps
```

#### 6.5 Estructura final en Pi

```
~/smart-home-prod/
├── docker-compose.yml          # Referencias a images de Docker Hub
├── .env                        # Todas las variables de entorno
├── data/                       # Volúmenes persistentes
│   ├── backend/
│   ├── baby-gifts-service/
│   │   ├── baby_gifts.db
│   │   └── gifts.json          # 🎁 Datos de Virchu preservados
│   ├── ac-service/
│   ├── vacaciones-service/
│   ├── casita-suenos/
│   ├── zigbee2mqtt/
│   ├── mosquitto/
│   └── nginx/
└── infrastructure/
    ├── nginx/
    │   ├── nginx.conf
    │   ├── conf.d/
    │   ├── .htpasswd
    │   └── certs/
    └── mosquitto/
        └── mosquitto.conf
```

**Lo que se ELIMINA**:
- ❌ Todo el código fuente Python
- ❌ Repositorios Git
- ❌ Tests
- ❌ Archivos de desarrollo

**Lo que PERMANECE**:
- ✅ Datos persistentes (data/)
- ✅ Configuración de infra (nginx, mosquitto)
- ✅ Variables de entorno (.env)
- ✅ Docker y docker-compose

---

### Fase 7: Validación
**Estado**: ⬜ Pendiente
**Duración estimada**: 1-2 horas
**Dependencias**: Fase 6 completada

#### 7.1 Tests de integración automáticos

```bash
# En la Pi
cd ~/smart-home-prod

# Verificar todos los contenedores running
docker ps --format "table {{.Names}}\t{{.Status}}"

# Verificar health checks
docker inspect --format='{{.Name}}: {{.State.Health.Status}}' $(docker ps -q) 2>/dev/null || echo "Some containers don't have health checks"

# Verificar logs por errores
docker-compose logs --tail=50 | grep -i error
```

#### 7.2 Tests manuales

| Test | Endpoint/Acción | Esperado |
|------|-----------------|----------|
| Dashboard | https://raspberrypi.local/ | Login funciona |
| AC Service | Dashboard → AC control | Muestra temperatura |
| Baby Gifts | /smart-home/baby-gifts | Lista de regalos de Virchu |
| Vacaciones | /smart-home/vacaciones | Planificador navidad |
| Casita | /api/casita/ | Monitor pisos |
| Zigbee | Dashboard → Sensores | Lecturas actuales |

#### 7.3 Verificar datos preservados

```bash
# Verificar que gifts.json tiene los datos correctos
cat ~/smart-home-prod/data/baby-gifts-service/gifts.json | jq '.gifts | length'
# Debería mostrar el número de regalos esperado (17 según el backup)

# Verificar base de datos de invitaciones
sqlite3 ~/smart-home-prod/data/baby-gifts-service/baby_gifts.db "SELECT COUNT(*) FROM invitations;"
```

#### 7.4 Test de deploy desde Kiro

En una sesión de Kiro, probar:
```
deploy baby-gifts-service
```

Verificar que:
- Se ejecuta `gh workflow run deploy.yml`
- El workflow aparece en GitHub Actions
- La Pi actualiza el servicio

---

### Fase 8: Documentación
**Estado**: ⬜ Pendiente
**Duración estimada**: 1 hora
**Dependencias**: Fase 7 completada

#### 8.1 Actualizar README.md

Añadir sección de deployment:
```markdown
## Deployment

### Requisitos
- GitHub CLI (`gh`) instalado y autenticado
- Acceso SSH a la Raspberry Pi

### Deploy manual desde GitHub
1. Ir a Actions → Deploy to Raspberry Pi
2. Click "Run workflow"
3. Seleccionar servicio
4. Click "Run workflow"

### Deploy desde Kiro
Simplemente escribe en el chat:
```
deploy <servicio>
```
Servicios disponibles: all, dashboard, ac-service, baby-gifts-service, vacaciones-service, casita-suenos
```

#### 8.2 Actualizar steering files locales

Los steering files están en `.kiro/steering/` y NO se suben a GitHub.
Actualizar `project-standards.md` con:
- Nueva estructura de carpetas
- Nuevo flujo de deployment
- Comandos útiles

#### 8.3 Actualizar .gitignore

```gitignore
# Kiro configuration (local only)
.kiro/

# Environment files
.env
.env.*
!.env.example

# Steering files (if any outside .kiro)
*.steering.md
```

#### 8.4 Limpiar archivos de steering de GitHub

```bash
# Si hay archivos steering en el repo, eliminarlos
git rm --cached .kiro/ 2>/dev/null || true
git rm --cached "*steering*" 2>/dev/null || true
git commit -m "chore: remove steering files from repo"
git push origin main
```

#### 8.5 Crear tag de versión

```bash
git tag -a post-migration-v1 -m "CI/CD migration complete - Docker Hub deployment"
git push origin post-migration-v1
```

---

## Checklist de Validación Final

### Funcionalidad
- [ ] Dashboard accesible y funcional
- [ ] Todos los servicios responden en sus endpoints
- [ ] AC control funciona (MELCloud)
- [ ] Baby gifts muestra la lista correcta (datos de Virchu)
- [ ] Sensores Zigbee reportan datos
- [ ] Autenticación funciona

### CI/CD
- [ ] Push a GitHub dispara tests
- [ ] Tests detectan cambios por servicio
- [ ] Deploy manual desde GitHub UI funciona
- [ ] Deploy desde Kiro funciona
- [ ] Imágenes se actualizan correctamente en Pi

### Datos
- [ ] gifts.json preservado con todos los regalos
- [ ] baby_gifts.db preservado con invitaciones
- [ ] Todos los .env configurados correctamente
- [ ] Credenciales funcionan (MELCloud, Telegram, Gmail)

### Limpieza
- [ ] No hay código fuente en la Pi
- [ ] .kiro/ no está en GitHub
- [ ] Steering files no están en GitHub
- [ ] Espacio liberado en Pi

---

## Rollback Plan

### Si falla en Fase 6 (deploy Pi):
```bash
# Restaurar desde backup
cd ~
tar -xzvf backup_data_YYYYMMDD_HHMMSS.tar.gz
# Reclonar repo y rebuild
git clone <repo> ~/projects/smart-home
cd ~/projects/smart-home
docker-compose up -d --build
```

### Si falla en Fases 1-5 (local):
```bash
git checkout pre-migration-v1
```

---

## Preguntas Pendientes

- [ ] ¿Usuario de Docker Hub a usar?
- [ ] ¿Email para notificaciones de CI?
- [ ] ¿IP fija de la Pi o usar Tailscale hostname?

---

## Tiempo Total Estimado

| Fase | Tiempo |
|------|--------|
| Fase 0: Preparación | 30 min |
| Fase 1: Reestructuración | 2-3 horas |
| Fase 2: Dockerfiles | 1-2 horas |
| Fase 3: Docker Hub | 30 min |
| Fase 4: Tests CI | 1-2 horas |
| Fase 5: Deploy CI | 2-3 horas |
| Fase 6: Deploy Pi | 2-3 horas |
| Fase 7: Validación | 1-2 horas |
| Fase 8: Documentación | 1 hora |
| **TOTAL** | **11-17 horas** |

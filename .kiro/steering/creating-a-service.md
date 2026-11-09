---
inclusion: fileMatch
fileMatchPattern: "services/**|.github/workflows/**|dashboard/**|infrastructure/nginx/**|docker-compose*.yml|docs/API.md|scripts/validate-services.ps1"
---
# Alta y mantenimiento de servicios — estándar (SSOT por capas)

Procedimiento para **crear, integrar y mantener** servicios en Cuchi Casa. Aplica al trabajar en `services/`, dashboard, nginx, CI, compose, `docs/API.md` o el validador.

## Modelo de “fuente de verdad” (qué manda en cada decisión)
| Capa | SSOT | Decide | Regla |
|---|---|---|---|
| Despliegue producción | `docker-compose.prod.yml` | Contenedores/imágenes, `container_name`, red, `expose/ports`, volúmenes `./data/<svc>`, healthcheck, env, `depends_on` | **Todo** lo que corre en la Pi debe estar aquí. Es el inventario canónico. |
| Contrato de integración (servicios propios) | `services/<nombre>/service.toml` | Clase, puerto, health, flags de dashboard/nginx/CI/deploy | Complementa compose; **no** lo reemplaza. Nuevos servicios: obligatorio. Existentes: añadir al tocarlos. |
| Código | **Directorio propio por servicio** (`services/<nombre>/` por defecto) | Implementación, Dockerfile, tests, manifiesto | **Cada servicio debe tener su propio directorio** (no mezclar código de servicios distintos). Si el código vive fuera de `services/` (p. ej. `dashboard/`), declararlo en `service.toml` (`code_path`) y mantener un manifiesto/registro claro. |
| Vistas/integraciones | nginx, `APP_CATALOGUE`/`DEPLOY_SERVICES`, `CONTROLLABLE_CONTAINERS`, `api/health.py`, `ci.yml`, `dev.ps1`, `docs/API.md` | Exposición, UI, control, monitorización, build | **Deben concordar** con (1)+(2). No son SSOT: si hay conflicto, corregir la vista. |
| Estado real | `docker ps` / `/api/health/*` en Pi | Qué pasa ahora | Observabilidad, no definición. |

**Prohibido:** listas hardcodeadas de servicios en el agente global u otros docs sin derivarlas de las fuentes anteriores. El agente `smart-home` solo documenta *cómo descubrir* servicios y apunta a estos steerings.

## Clases de servicio (define qué hay que registrar)
| Clase | Ejemplo | Registro mínimo |
|---|---|---|
| `infrastructure` | redis, mosquitto, nginx, docker-socket-proxy | compose prod (+ healthcheck/operación). Dashboard/CI solo si el diseño lo exige. |
| `app` (microservicio) | ac-service, calendar-service, metrics-service | directorio propio en `services/<n>/`, `service.toml`, compose, Dockerfile, `GET /health`, CI, `dev.ps1` si hay tests; nginx/dashboard según flags. |
| `app` con tile/control | portfolio, casita, ac, baby-gifts | lo anterior + `APP_CATALOGUE`, `DEPLOY_SERVICES` (si aplica), `CONTROLLABLE_CONTAINERS`, health proxy + `/all` + contratos + coherencia. |
| `wrapper` / `external` | vaultwarden, immich stack | compose/proxy según caso; integración selectiva; mantener directorio/manifiesto cuando haya código o configuración propia. |

## Checklist — alta completa de un servicio nuevo
Marcar solo lo que aplique a la **clase/flags** del servicio.

- [ ] **Directorio propio:** crear `services/<nombre>/` (o ruta propia documentada) con `service.toml`. No ubicar el servicio dentro del directorio de otro servicio.
- [ ] **Contrato:** `services/<nombre>/service.toml` desde `_template` (clase, key, puerto, health, flags, `code_path`).
- [ ] **Despliegue (SSOT):** `docker-compose.prod.yml`; `docker-compose.yml`/override/citest si participa. Imagen `egnal/smart-home-<nombre>:latest` cuando aplique. Volumen `./data/<svc>`; si non-root+SQLite, documentar/ejecutar `mkdir -p` + `chown 1000:1000` en deploy.
- [ ] **Código:** Dockerfile, `requirements.txt`, `src/main.py`, `tests/` en el directorio del servicio. `GET /health` (+ alias si se usa).
- [ ] **Nginx** (si `nginx.exposed`): rutas `/static/<svc>/` antes de `/static/` general, SPA `/smart-home/<svc>`, API `/api/<svc>/`, health pública si aplica, `auth_request` según patrón.
- [ ] **Dashboard** (solo si `dashboard.enabled`):
  - [ ] `dashboard/src/static/dashboard.html`: `APP_CATALOGUE` y/o `DEPLOY_SERVICES` según flags.
  - [ ] `dashboard/src/system/containers.py`: `CONTROLLABLE_CONTAINERS` (clave = *app key* lógico) si `controllable`.
  - [ ] `dashboard/src/api/health.py`: ruta health, caché, entrada en `/all` si aplica.
  - [ ] `dashboard/src/api/routes.py` (o capa equivalente): proxies de API para Swagger unificado si expone API.
  - [ ] `dashboard/src/main.py`: tag OpenAPI.
  - [ ] Tests: `dashboard/tests/unit/test_catalogue_coherence.py` (mappings/allowlists) y `dashboard/tests/unit/api/test_service_contracts.py` si aplica.
- [ ] **CI/CD:** `.github/workflows/ci.yml` (paths-filter, outputs/case, matrix `add_service`, job lint+test+hadolint+pytest gated, quality-gate `needs`+`check_job`, verify, `workflow_dispatch`). `dev.ps1` si hay tests/lint locales.
- [ ] **Docs:** `docs/API.md`; `README.md`/`DOCKER.md` si el cambio es visible.
- [ ] **Validación:** `scripts/validate-services.ps1` (o equivalente), tests de coherencia/contratos, `ruff`/`bandit`/`pytest` del servicio, `docker compose config` donde aplique. `git status` limpio de temporales.

## Snippets de referencia (adaptar, no copiar ciegamente)

### `service.toml` mínimo (servicios propios)
Ver `services/_template/service.toml`.

### `docker-compose.prod.yml`
```yaml
  <service-name>:
    image: egnal/smart-home-<service-name>:latest
    container_name: <service-name>
    restart: on-failure:5
    mem_limit: <Xm>
    memswap_limit: <Xm>
    expose:
      - <port>
    volumes:
      - ./data/<service-name>:/app/data
    env_file:
      - .env
    environment:
      - TZ=Europe/Madrid
    networks:
      - smart-home
    healthcheck:
      test: ["CMD", "python3", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:<port>/health', timeout=3)"]
      interval: 60s
      timeout: 5s
      retries: 3
      start_period: 30s
```

### FastAPI — endpoints base
```python
app = FastAPI(title="<Service Name> Service", version="1.0.0", docs_url="/swagger", redoc_url="/redoc")

@app.get("/health")
def health():
    return {"online": True, "service": "<service>"}

@app.get("/api/health/<service>")  # alias si el dashboard/contrato lo usa
def health_api():
    return {"online": True, "service": "<service>"}
```
SPA: cache-busting suave en HTML servido (`<!-- v:timestamp -->`, `Cache-Control: no-cache`). Montar estáticos en ruta específica (`/static/<service>`) para evitar colisiones con dashboard.

### Nginx (orden importa)
```nginx
# 1) Estáticos del servicio ANTES de location /static/ general
location /static/<service>/ {
    set $svc_host "<service-name>";
    proxy_pass http://$svc_host:<port>;
    proxy_set_header Host $host;
    proxy_http_version 1.1;
}
# 2) SPA + API + health (auth_request según corresponda)
location /smart-home/<service> { /* auth_request + proxy */ }
location /api/<service>/       { /* auth_request + proxy */ }
location = /api/health/<service> { /* proxy, sin auth si es health público interno */ }
```

### Dashboard — puntos críticos
- **`APP_CATALOGUE`** (`dashboard.html`): `url`, `nameKey`/`descKey`, `statusUrl`, `getStatus`. Solo tiles de usuario.
- **`DEPLOY_SERVICES`** (`dashboard.html`): app key → nombre usado por CI/workflow_dispatch; backend valida allow-list.
- **`CONTROLLABLE_CONTAINERS`** (`system/containers.py`): app key lógico → `[containers]`. Solo controlables.
- **`api/health.py`**: función por servicio, caché, y entrada en `/all` si aplica. **Coherencia obligatoria** con `test_catalogue_coherence.py` (mapeos key↔ruta, allowlists de infra, keys de `/all`) y `test_service_contracts.py`.

### CI (`.github/workflows/ci.yml`)
1. `paths-filter`: `<service>: - 'services/<service-name>/**'` (+ deps compartidas si tocan `libs/`).
2. Outputs/flags en `prepare` + bloque de auto-detección/case.
3. Matrix: `add_service "<service-name>" "egnal/smart-home-<service-name>" "./services/<service-name>"` (o contexto/dockerfile según patrón).
4. Job `lint-and-test-<service>` (gated), `quality-gate` `needs` + `check_job`.
5. `verify` health y `workflow_dispatch` option.
6. Deploy: `mkdir -p`/`chown` de `data/<service>` antes de `up` cuando aplique.

## Mantenimiento de servicios existentes
- **Conocer despliegue:** `docker-compose.prod.yml` + `scripts/validate-services.ps1`.
- **Conocer integración:** tests `test_catalogue_coherence` / `test_service_contracts`.
- **Al modificar un servicio:** si no tiene `service.toml`, crearlo; corregir drift en compose/nginx/dashboard/CI/docs en el mismo cambio.
- **Revisión periódica:** ejecutar validador y tests de coherencia; comparar tiles/health con servicios reales de prod.

## Notas
- `valheim-server` (juego) y stacks externos pueden no seguir la plantilla FastAPI; documentar clase `external`/`wrapper` y registrar solo lo necesario.
- No modificar la Pi directamente: GitHub Actions → Docker → Pi.

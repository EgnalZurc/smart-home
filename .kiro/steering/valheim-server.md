---
inclusion: fileMatch
fileMatchPattern: "services/valheim-*/**"
---
# Valheim Server — Reference (VLH-1)

## Architecture (updated 2026-10-02)

| Component | Runs on | Purpose |
|-----------|---------|---------|
| **valheim-server** | **EgnalPC** (Windows) | Game server — Docker container `lloesche/valheim-server:latest` |
| **valheim-admin** | Raspberry Pi | Admin UI + API — communicates with pc-agent on EgnalPC |
| **pc-agent** | EgnalPC (Windows) | Controls valheim-server container, reports status |

⚠️ **valheim-server NO longer runs on the Pi.** It was moved to EgnalPC for better performance (native x86_64 instead of Box64 emulation).

## Network topology
```
User → nginx (Pi) → valheim-admin (Pi) → pc-agent (EgnalPC:8090) → valheim-server (Docker)
                                                                 ↓
Game clients → EgnalPC:2456-2458 UDP (via Join Code / crossplay)
```

## Quick reference
| Item | Value |
|------|-------|
| Image | `lloesche/valheim-server:latest` (x86_64) |
| Host | EgnalPC (192.168.1.164) |
| Admin UI | `https://raspberrypi.tailaa37cd.ts.net/valheim-admin/` |
| World saves | `D:\Valheim\data\worlds_local\` on EgnalPC |
| Ports | 2456-2458 UDP |
| Visible to | SUPER + GAMER profiles |

## Configuration
Server settings are managed via pc-agent API or directly in Docker environment on EgnalPC.

| Variable | Description |
|----------|-------------|
| `SERVER_NAME` | Visible in Steam |
| `WORLD_NAME` | Must match folder name in worlds_local |
| `SERVER_PASS` | Min 5 characters |
| `CROSSPLAY` | `true` = Join Code (no port forward needed) |

## How to connect (crossplay)
1. Valheim → **Start Game** → select character → **Start**
2. **Join Game** tab → **Add Server**
3. Enter **Join Code** (6 digits, visible in valheim-admin UI)
4. Select server → **Connect** → enter password

⚠️ Join Code changes on every restart.

## Valheim Admin UI (on Pi)
- View status, Join Code, connected players (via pc-agent)
- Start/stop server remotely
- View logs

## pc-agent endpoints (EgnalPC:8090)
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/valheim/status` | GET | Container status, players, join code |
| `/valheim/start` | POST | Start the server |
| `/valheim/stop` | POST | Stop the server |
| `/valheim/logs` | GET | Game logs |

## Important notes
- **Pi has NO valheim-server container** — only valheim-admin
- Server control goes through pc-agent (HTTP) not direct Docker commands
- EgnalPC must be in "Modo Servidor" for the server to be accessible
- World saves are on EgnalPC local disk, not on the Pi

## Incident 2026-11-25 (mods desinstalados)
- El mod `OdinLookedAway` (DLL del 06-oct) es incompatible con Valheim `l-1.0.30`: `ZDOExtraData.GetData` cambió su firma (ahora recibe `Version.World`) y los parches `RecordLoadPatch` / `NetworkBoundaryPatch` lanzan `MissingMethodException` tanto al cargar el mundo (servidor: bucle de caída cada ~35 s) como al deserializar ZDOs (cliente: paquete de estructuras descartado, "edificios destruidos").
- `OdinLookedAway` eliminado de ambos lados: servidor (`server_data/bepinex/plugins-disabled/`) y cliente (`BepInEx/plugins-disabled/`). No se recompilan los DLLs.
- pc-agent `/valheim/status` lee `docker logs` (fuente viva) y reporta `state` (`ready`/`starting`/`error`/`stopped`), `last_error` y `join_code` real; `/valheim/logs` prioriza el contenedor. La UI de valheim-admin muestra ese estado en vez de "Online".
- El mundo en disco nunca se guardó dañado: `_main.*` de `prueba2` sin cambios desde 24/11 18:56.

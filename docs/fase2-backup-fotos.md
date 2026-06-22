# Fase 2: Backup de Fotos

## Objetivo

Backup automático de fotos y vídeos de 2 teléfonos Android al servidor central. Permite
liberar espacio en los teléfonos con la seguridad de que todo está respaldado localmente.

## Contexto

Los teléfonos acumulan fotos y vídeos que ocupan cada vez más espacio. Las opciones cloud
(Google Photos, iCloud) tienen límites de almacenamiento gratuito y costes recurrentes.
Una solución local elimina esos costes y mantiene la privacidad.

## Requerimientos

| # | Requerimiento |
|---|---|
| F2.1 | Sync automático de fotos/vídeos de 2 Android al servidor |
| F2.2 | Copia unidireccional: teléfono → servidor |
| F2.3 | Borrar en teléfono NO borra en servidor |
| F2.4 | Sync automático cuando teléfono está en WiFi casa |
| F2.5 | Estándar y ligero (no requiere mucha RAM/CPU) |
| F2.6 | Sin dependencia de servicios cloud ni suscripciones |
| F2.7 | Almacenamiento suficiente (≥256GB) |

## Solución: Syncthing

**Syncthing** es un programa de sincronización P2P, open-source, cifrado, sin servidor central
de terceros.

### ¿Por qué Syncthing?

| Criterio | Syncthing | Immich | Google Photos |
|---|---|---|---|
| RAM necesaria | ~50-100MB | ≥6GB | N/A (cloud) |
| Funciona en Pi 5 2GB | ✓ | ✗ (muy justo) | N/A |
| App Android | ✓ (gratuita) | ✓ | ✓ |
| Galería web | ✗ (solo archivos) | ✓ (excelente) | ✓ |
| Privacidad | Total (local) | Total (local) | Google |
| Coste recurrente | 0€ | 0€ | Desde 2€/mes |
| Complejidad | Baja | Alta | Ninguna |

**Trade-off:** Syncthing no tiene galería web bonita para ver las fotos. Si en el futuro
quieres navegar fotos desde el navegador, se puede añadir PhotoPrism o Photoview como
contenedor adicional (requiere más RAM, posible upgrade a Pi 5 4GB).

### Funcionamiento

1. **Teléfono A** (Syncthing-Fork Android): carpeta DCIM configurada como "Send Only".
2. **Teléfono B** (Syncthing-Fork Android): carpeta DCIM configurada como "Send Only".
3. **Servidor** (Syncthing en Docker): carpetas configuradas como "Receive Only".
4. Cuando un teléfono está en WiFi de casa, las fotos nuevas se copian automáticamente.
5. Si borras una foto del teléfono, sigue en el servidor (Send Only + Receive Only = no propaga borrado).

### Almacenamiento

Las fotos se guardan en un SSD externo conectado por USB 3.0 a la Raspberry Pi.

**¿Por qué SSD y no HDD?**
- Sin ruido (no hay piezas móviles).
- Menos consumo (importante en una Pi).
- Más resistente a golpes.
- 256GB es suficiente para ~50.000 fotos a 5MB/foto o ~25h de vídeo 1080p.

## Hardware

| Componente | Modelo | Precio aprox. |
|---|---|---|
| SSD externo USB 3.0 256GB | Kingston XS1000 / Samsung T7 | ~35€ |
| SSD externo USB 3.0 1TB | Kingston XS1000 / Samsung T7 | ~70€ |

**Elegir tamaño según uso:**
- Si principalmente fotos: 256GB sobra para años.
- Si mucho vídeo 4K: considerar 1TB.

## Configuración

### Docker Compose (añadir al compose existente)

```yaml
syncthing:
  image: syncthing/syncthing:latest
  container_name: syncthing
  hostname: smart-home-sync
  environment:
    - PUID=1000
    - PGID=1000
  volumes:
    - ./syncthing/config:/var/syncthing/config
    - /mnt/backup-ssd/fotos:/var/syncthing/data
  ports:
    - 8384:8384    # Web UI
    - 22000:22000  # Sync protocol
    - 21027:21027/udp  # Discovery
  restart: unless-stopped
```

### Montaje del SSD

```bash
# Identificar el SSD
lsblk

# Formatear (solo la primera vez)
sudo mkfs.ext4 /dev/sda1

# Montar
sudo mkdir -p /mnt/backup-ssd
sudo mount /dev/sda1 /mnt/backup-ssd

# Montaje automático (añadir a /etc/fstab)
UUID=xxxx-xxxx /mnt/backup-ssd ext4 defaults,nofail 0 2
```

### Configuración en teléfonos

1. Instalar Syncthing-Fork (F-Droid o Play Store).
2. Abrir app → Añadir dispositivo → escanear QR del servidor.
3. Compartir carpeta DCIM/Camera → tipo "Send Only".
4. Condiciones de ejecución: solo en WiFi, solo cargando (opcional).

## Integración con Web UI

Nueva sección/tab "Backup" en la PWA:
- Estado de sincronización (última sync de cada teléfono).
- Espacio usado / disponible en el SSD.
- Número de archivos respaldados.
- Enlace a la interfaz web de Syncthing (puerto 8384) para config avanzada.

## Acceso remoto

Vía Tailscale (ya instalado en la infraestructura base), puedes:
- Ver el estado del backup desde fuera de casa.
- Forzar una sincronización.
- Acceder a la interfaz web de Syncthing.

**Nota:** Syncthing también puede sincronizar vía Tailscale (no solo WiFi local), pero
consumiría datos móviles. Recomendado dejarlo solo en WiFi.

## Dependencias

- Infraestructura base operativa (Docker, Tailscale).
- No depende de la fase 0 ni 1 (puede implementarse de forma independiente).
- Solo necesita un puerto USB libre en la Pi (hay varios disponibles).

## Coste

| Concepto | Mínimo | Máximo |
|---|---|---|
| SSD externo 256GB | 35€ | - |
| SSD externo 1TB | - | 70€ |
| Syncthing (software) | 0€ | 0€ |
| **Total fase 2** | **35€** | **70€** |

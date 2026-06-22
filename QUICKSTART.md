# Quick Start Guide

Guía rápida para poner en marcha el sistema Smart Home Control en menos de 10 minutos.

---

## 🎯 Pre-requisitos

- Raspberry Pi 5 (o compatible) con Raspberry Pi OS
- Docker + Docker Compose instalados
- SONOFF ZBDongle-E V2 conectado por USB
- 5 sensores SONOFF SNZB-02D emparejados
- Cuenta MELCloud con AC Mitsubishi configurado

---

## 🚀 Instalación Rápida

### 1️⃣ Clonar repositorio

```bash
git clone https://github.com/EgnalZurc/smart-home.git
cd smart-home
```

### 2️⃣ Configurar credenciales

```bash
cp .env.example .env
nano .env
```

**Editar `.env` con tus datos:**
```env
MELCLOUD_EMAIL=tu_email@ejemplo.com
MELCLOUD_PASSWORD=tu_password
MELCLOUD_DEVICE_ID=123456789
MELCLOUD_BUILDING_ID=987654
ESIOS_API_KEY=                    # Opcional
```

💡 **Obtener IDs MELCloud:** Abrir app MELCloud → Ver URL o configuración del dispositivo

### 3️⃣ Verificar dongle Zigbee

```bash
ls -l /dev/ttyUSB* /dev/ttyACM*
```

Si aparece como `/dev/ttyACM0`, editar `docker-compose.yml`:
```yaml
devices:
  - /dev/ttyACM0:/dev/ttyACM0  # Cambiar si es necesario
```

### 4️⃣ Iniciar servicios

```bash
docker-compose up -d --build
```

⏱️ Primera vez tarda ~5 minutos (descarga imágenes y construye)

### 5️⃣ Verificar logs

```bash
docker-compose logs -f
```

**Buscar en logs:**
- ✅ `zigbee2mqtt` - "Zigbee2MQTT started"
- ✅ `mosquitto` - "Running"
- ✅ `backend` - "Application startup complete"

Presionar `Ctrl+C` para salir de logs

### 6️⃣ Acceder a la Web UI

```bash
# Obtener IP de la Raspberry
hostname -I
```

Abrir navegador: `http://<IP_DE_LA_PI>:8080`

---

## ✅ Verificación

### Dashboard debe mostrar:

- 🌡️ **Temperatura Media** (promedio de 5 sensores)
- 💧 **Humedad Media**
- 🌍 **Temperatura Exterior** (Madrid)
- ❄️ **Estado del AC** (ON/OFF, modo, velocidad ventilador)
- 🤖 **Controlador** (decisión actual)
- ⚡ **Energía 24h** (kWh y €)
- 📊 **5 sensores** con temperatura, humedad, batería

### Si algo falla:

```bash
# Ver logs de un servicio específico
docker logs smart-home-backend --tail 50
docker logs zigbee2mqtt --tail 50

# Reiniciar servicios
docker-compose restart

# Ver estado
docker-compose ps
```

---

## 🎮 Uso Básico

### Cambiar temperatura objetivo

1. Click en "TEMP. OBJETIVO"
2. Usar botones + / - para ajustar (19-30°C)
3. Sistema ajusta automáticamente

### Forzar AC ON

1. Click en "FORZAR ON"
2. Elegir modo (COLD/HOT/DRY/FAN)
3. Elegir velocidad ventilador (Bajo/Medio/Alto/Auto)
4. Elegir temperatura
5. Click "Confirmar"

### Forzar AC OFF

1. Click en "FORZAR OFF"
2. Confirmar

### Ver estadísticas de energía

1. Click en widget "ENERGÍA (24h)"
2. Ver gráficas horarias y mensuales

### Ver detalle de sensor

1. Click en cualquier sensor
2. Ver gráficas de temperatura y humedad

---

## 🔧 Comandos Útiles

```bash
# Ver logs en tiempo real
docker-compose logs -f

# Reiniciar todo
docker-compose restart

# Parar todo
docker-compose down

# Actualizar (tras git pull)
docker-compose down
docker-compose up -d --build

# Ver uso de recursos
docker stats

# Backup de datos
docker run --rm -v smart-home_backend_data:/data -v $(pwd):/backup \
  alpine tar czf /backup/backup.tar.gz -C /data .
```

---

## 📚 Más Información

- **Guía completa de despliegue:** [DEPLOY.md](DEPLOY.md)
- **Requerimientos del proyecto:** [docs/REQUERIMIENTOS-COMPLETOS.md](docs/REQUERIMIENTOS-COMPLETOS.md)
- **Diseño Fase 0:** [docs/fase0-ac-override.md](docs/fase0-ac-override.md)
- **Troubleshooting:** Ver sección en [DEPLOY.md](DEPLOY.md#-troubleshooting)

---

## 🆘 Problemas Comunes

### "Port 8080 already in use"

```bash
# Ver qué usa el puerto
sudo netstat -tlnp | grep 8080

# Cambiar puerto en docker-compose.yml
ports:
  - "8888:8080"  # Usar 8888 en lugar de 8080
```

### "Cannot connect to MELCloud"

- Verificar credenciales en `.env`
- Verificar que AC está online en app MELCloud
- Ver logs: `docker logs smart-home-backend | grep -i melcloud`

### "No sensors detected"

- Verificar dongle USB: `ls -l /dev/ttyUSB*`
- Ver logs: `docker logs zigbee2mqtt | grep -i error`
- Verificar puerto en `infrastructure/zigbee2mqtt/configuration.yaml`

---

**¿Todo funcionando?** 🎉

¡Enhorabuena! Tu sistema Smart Home está operativo.

**Próximos pasos:**
- Configurar IP fija en la Raspberry Pi
- Instalar Tailscale para acceso remoto
- Configurar API key ESIOS para precios reales
- Explorar fases futuras (humedad, backup fotos)

---

**Tiempo estimado:** 10-15 minutos  
**Última actualización:** 22 de junio de 2026

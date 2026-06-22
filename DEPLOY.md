# Guía de Despliegue - Raspberry Pi

Esta guía explica cómo desplegar el proyecto Smart Home Control en una Raspberry Pi 5.

---

## 📋 Pre-requisitos

### Hardware
- Raspberry Pi 5 (4GB recomendado)
- SONOFF ZBDongle-E V2 (coordinador Zigbee)
- Tarjeta microSD (mínimo 32GB)
- 5 sensores SONOFF SNZB-02D emparejados

### Software
- Raspberry Pi OS Bookworm 64-bit
- Docker + Docker Compose
- Git

---

## 🚀 Instalación desde Cero

### 1. Preparar Raspberry Pi

```bash
# Actualizar sistema
sudo apt update && sudo apt upgrade -y

# Instalar dependencias
sudo apt install -y git curl

# Instalar Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker $USER

# Instalar Docker Compose
sudo apt install -y docker-compose

# Logout y login para aplicar grupo docker
```

### 2. Clonar Repositorio

```bash
cd ~
git clone https://github.com/EgnalZurc/smart-home.git
cd smart-home
```

### 3. Configurar Variables de Entorno

```bash
# Copiar plantilla
cp .env.example .env

# Editar con tus credenciales
nano .env
```

**Configurar en `.env`:**
- `MELCLOUD_EMAIL`: Tu email de MELCloud
- `MELCLOUD_PASSWORD`: Tu contraseña de MELCloud
- `MELCLOUD_DEVICE_ID`: ID de tu dispositivo AC (ver app MELCloud)
- `MELCLOUD_BUILDING_ID`: ID de tu edificio (ver app MELCloud)
- `ESIOS_API_KEY`: (Opcional) API key de ESIOS para precios reales

**Obtener IDs de MELCloud:**
1. Abrir app MELCloud en móvil
2. Seleccionar tu AC
3. Los IDs aparecen en la URL o configuración

**Obtener API Key ESIOS (opcional):**
1. Registrarse en https://www.esios.ree.es/es/pagina/api
2. Solicitar API key (gratuita)
3. Añadir a `.env`

### 4. Verificar Dongle Zigbee

```bash
# Conectar el ZBDongle-E V2 a USB
# Verificar que se detecta
ls -l /dev/ttyUSB*

# Debería aparecer /dev/ttyUSB0
# Si aparece como /dev/ttyACM0, editar docker-compose.yml
```

### 5. Configurar Zigbee2MQTT

```bash
# Editar configuración Zigbee2MQTT
nano infrastructure/zigbee2mqtt/configuration.yaml
```

**Verificar puerto serie:**
```yaml
serial:
  port: /dev/ttyACM0  # Cambiar según tu dongle (ttyUSB0 o ttyACM0)
```

### 6. Iniciar Servicios

```bash
# Construir y arrancar todos los contenedores
docker-compose up -d --build

# Ver logs
docker-compose logs -f

# Verificar que todo está corriendo
docker-compose ps
```

**Servicios que deben estar UP:**
- `mosquitto` (broker MQTT)
- `zigbee2mqtt` (gateway Zigbee)
- `smart-home-backend` (backend + web UI)

### 7. Acceder a la Web UI

```bash
# Desde la misma red WiFi
http://<IP_DE_LA_RASPBERRY>:8080

# O si estás en la Raspberry
http://localhost:8080
```

**Obtener IP de la Raspberry:**
```bash
hostname -I
```

### 8. Verificar Sensores

1. Abrir web UI
2. Los 5 sensores deben aparecer en la pantalla principal
3. Verificar que muestran temperatura y humedad actualizadas
4. Verificar colores (verde si conectado, rojo si desconectado)

---

## 🔧 Configuración Post-Instalación

### Emparejar Sensores (si no están emparejados)

1. Abrir Zigbee2MQTT UI: `http://<IP>:8080/zigbee` (si está habilitado)
2. O usar logs: `docker logs zigbee2mqtt -f`
3. Poner sensores en modo emparejamiento (botón 5 segundos)
4. Renombrar sensores según ubicación en `configuration.yaml`

### Configurar IP Fija (recomendado)

Editar `/etc/dhcpcd.conf`:
```bash
sudo nano /etc/dhcpcd.conf
```

Añadir al final:
```
interface wlan0
static ip_address=192.168.1.163/24
static routers=192.168.1.1
static domain_name_servers=192.168.1.1 8.8.8.8
```

Reiniciar:
```bash
sudo reboot
```

### Habilitar Inicio Automático

Docker Compose con `restart: unless-stopped` ya inicia automáticamente al arrancar la Pi.

Verificar:
```bash
# Ver política de reinicio
docker inspect smart-home-backend | grep -i restart
```

---

## 📊 Monitorización y Mantenimiento

### Ver Logs en Tiempo Real

```bash
# Todos los servicios
docker-compose logs -f

# Solo backend
docker logs smart-home-backend -f

# Solo Zigbee2MQTT
docker logs zigbee2mqtt -f
```

### Reiniciar Servicios

```bash
# Reiniciar todos
docker-compose restart

# Reiniciar solo backend
docker restart smart-home-backend

# Parar todo
docker-compose down

# Iniciar todo
docker-compose up -d
```

### Actualizar a Nueva Versión

```bash
cd ~/smart-home
git pull
docker-compose down
docker-compose up -d --build
```

### Backup de Datos

```bash
# Backup de volúmenes Docker
docker run --rm -v smart-home_backend_data:/data -v $(pwd):/backup \
  alpine tar czf /backup/backend_data_backup.tar.gz -C /data .

# Backup de configuración Zigbee2MQTT
tar czf zigbee2mqtt_backup.tar.gz infrastructure/zigbee2mqtt/

# Backup de .env (credenciales)
cp .env .env.backup
```

### Restaurar Backup

```bash
# Restaurar volumen backend
docker run --rm -v smart-home_backend_data:/data -v $(pwd):/backup \
  alpine sh -c "cd /data && tar xzf /backup/backend_data_backup.tar.gz"

# Restaurar Zigbee2MQTT
tar xzf zigbee2mqtt_backup.tar.gz
```

---

## 🐛 Troubleshooting

### Problema: Sensores no aparecen

**Causas posibles:**
- Zigbee2MQTT no inició correctamente
- Dongle Zigbee no detectado
- Sensores no emparejados

**Solución:**
```bash
# Verificar logs Zigbee2MQTT
docker logs zigbee2mqtt --tail 50

# Verificar puerto serie
ls -l /dev/ttyUSB* /dev/ttyACM*

# Verificar configuración
cat infrastructure/zigbee2mqtt/configuration.yaml
```

### Problema: Backend no inicia

**Causas posibles:**
- Credenciales MELCloud incorrectas
- MQTT broker no disponible
- Puerto 8080 ocupado

**Solución:**
```bash
# Ver logs detallados
docker logs smart-home-backend --tail 50

# Verificar .env
cat .env

# Verificar puertos
sudo netstat -tlnp | grep 8080
```

### Problema: Web UI no carga

**Causas posibles:**
- Backend no corriendo
- Firewall bloqueando puerto 8080
- IP incorrecta

**Solución:**
```bash
# Verificar servicios
docker-compose ps

# Verificar desde la misma Pi
curl http://localhost:8080

# Verificar firewall (Raspberry Pi OS no tiene firewall por defecto)
sudo iptables -L
```

### Problema: AC no responde

**Causas posibles:**
- Credenciales MELCloud incorrectas
- AC no conectado a WiFi
- IDs de dispositivo incorrectos

**Solución:**
```bash
# Verificar logs del controlador
docker logs smart-home-backend | grep -i melcloud

# Test manual de API MELCloud
curl -X POST "https://app.melcloud.com/Mitsubishi.Wifi.Client/Login/ClientLogin" \
  -H "Content-Type: application/json" \
  -d '{"Email":"tu_email","Password":"tu_password"}'
```

### Problema: Precios energía no actualizan

**Causa:** API key ESIOS no configurada o incorrecta

**Solución:**
```bash
# Sistema funciona sin API key (usa precio mock 0.15€/kWh)
# Para usar precios reales, configurar ESIOS_API_KEY en .env

# Verificar logs
docker logs smart-home-backend | grep -i esios
```

---

## 🔐 Seguridad

### Cambiar Puerto (opcional)

Editar `docker-compose.yml`:
```yaml
backend:
  ports:
    - "8888:8080"  # Cambiar 8080 a otro puerto
```

### Acceso Remoto (Tailscale)

**Instalación Tailscale en Raspberry Pi:**
```bash
curl -fsSL https://tailscale.com/install.sh | sh
sudo tailscale up
```

**Acceso desde fuera de casa:**
1. Instalar Tailscale en tu móvil/PC
2. Conectar a la VPN
3. Acceder a `http://<IP_TAILSCALE_PI>:8080`

**IP Tailscale de la Pi:**
```bash
tailscale ip -4
```

---

## 📈 Optimización

### Reducir Uso de SD (recomendado)

```bash
# Limitar logs de Docker
sudo nano /etc/docker/daemon.json
```

Añadir:
```json
{
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "10m",
    "max-file": "3"
  }
}
```

Reiniciar Docker:
```bash
sudo systemctl restart docker
docker-compose up -d
```

### Monitorizar Recursos

```bash
# Uso de CPU/RAM
docker stats

# Uso de disco
df -h
du -sh infrastructure/zigbee2mqtt/log/

# Temperatura de la Pi
vcgencmd measure_temp
```

---

## 📚 Recursos

- **Documentación completa:** `docs/`
- **Requerimientos:** `docs/REQUERIMIENTOS-COMPLETOS.md`
- **Diseño fase 0:** `docs/fase0-ac-override.md`
- **Diseño energía:** `docs/DISEÑO-ENERGIA-F0.md`
- **README principal:** `README.md`

---

## 🆘 Soporte

Si encuentras problemas:
1. Revisar logs: `docker-compose logs -f`
2. Consultar esta guía de troubleshooting
3. Revisar issues en GitHub
4. Crear nuevo issue con logs y descripción del problema

---

**Última actualización:** 22 de junio de 2026  
**Versión:** 1.0 - Fase 0 Completa

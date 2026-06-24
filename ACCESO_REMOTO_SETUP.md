# Configuración de Acceso Remoto con DuckDNS + Nginx

## Resumen

Tu aplicación smart-home está ahora detrás de un reverse proxy Nginx que permite acceso a múltiples servicios con una sola URL.

## URLs Configuradas

- **App Principal (Control AC)**: http://cuchi-casa.duckdns.org/
- **Zigbee2MQTT (Configuración sensores)**: http://cuchi-casa.duckdns.org/zigbee
- **Health Check**: http://cuchi-casa.duckdns.org/health

## Estado Actual

✅ Nginx reverse proxy configurado
✅ DuckDNS dominio registrado: cuchi-casa.duckdns.org
✅ IP estática configurada: 192.168.1.163
⚠️ Port forwarding PENDIENTE (ver paso final)

## Arquitectura



## Servicios Docker Activos

1. **nginx-reverse-proxy** - Puerto 80 (acceso público)
2. **smart-home-backend** - Puerto 8080 (solo interno)
3. **zigbee2mqtt** - Puerto 8081 (solo interno)
4. **mosquitto** - Puerto 1883 (MQTT broker)

## Paso Final: Configurar Port Forwarding en el Router

### Necesitas abrir 1 solo puerto en tu router DIGI:

1. Accede al router: http://192.168.1.1

2. Ve a la sección de **Port Forwarding** / **NAT** / **Virtual Servers**

3. Crea una nueva regla:
   - **Nombre**: Smart Home HTTP
   - **Puerto externo**: 80
   - **IP interna**: 192.168.1.163
   - **Puerto interno**: 80
   - **Protocolo**: TCP

4. Guarda la configuración

5. **Verifica desde tu móvil (usando datos móviles, NO WiFi)**:
   - Abre: http://cuchi-casa.duckdns.org
   - Deberías ver tu aplicación de control AC

## Verificación Local

Desde la Raspberry Pi o cualquier dispositivo en tu red local:

OK
HTTP/1.1 405 Method Not Allowed
Server: nginx/1.31.2
Date: Wed, 24 Jun 2026 15:36:40 GMT
Content-Type: application/json
Content-Length: 31
Connection: keep-alive
allow: GET

HTTP/1.1 404 Not Found
Server: nginx/1.31.2
Date: Wed, 24 Jun 2026 15:36:40 GMT
Content-Type: text/html; charset=utf-8
Content-Length: 146
Connection: keep-alive
Content-Security-Policy: default-src 'none'
X-Content-Type-Options: nosniff


## Comandos Útiles

### Ver logs de Nginx
/docker-entrypoint.sh: /docker-entrypoint.d/ is not empty, will attempt to perform configuration
/docker-entrypoint.sh: Looking for shell scripts in /docker-entrypoint.d/
/docker-entrypoint.sh: Launching /docker-entrypoint.d/10-listen-on-ipv6-by-default.sh
10-listen-on-ipv6-by-default.sh: info: Getting the checksum of /etc/nginx/conf.d/default.conf
10-listen-on-ipv6-by-default.sh: info: Enabled listen on IPv6 in /etc/nginx/conf.d/default.conf
/docker-entrypoint.sh: Sourcing /docker-entrypoint.d/15-local-resolvers.envsh
/docker-entrypoint.sh: Launching /docker-entrypoint.d/20-envsubst-on-templates.sh
/docker-entrypoint.sh: Launching /docker-entrypoint.d/30-tune-worker-processes.sh
/docker-entrypoint.sh: Configuration complete; ready for start up
/docker-entrypoint.sh: /docker-entrypoint.d/ is not empty, will attempt to perform configuration
/docker-entrypoint.sh: Looking for shell scripts in /docker-entrypoint.d/
/docker-entrypoint.sh: Launching /docker-entrypoint.d/10-listen-on-ipv6-by-default.sh
10-listen-on-ipv6-by-default.sh: info: Getting the checksum of /etc/nginx/conf.d/default.conf
10-listen-on-ipv6-by-default.sh: info: Enabled listen on IPv6 in /etc/nginx/conf.d/default.conf
/docker-entrypoint.sh: Sourcing /docker-entrypoint.d/15-local-resolvers.envsh
/docker-entrypoint.sh: Launching /docker-entrypoint.d/20-envsubst-on-templates.sh
/docker-entrypoint.sh: Launching /docker-entrypoint.d/30-tune-worker-processes.sh
/docker-entrypoint.sh: Configuration complete; ready for start up

### Ver logs de acceso
172.18.0.1 - - [24/Jun/2026:15:33:02 +0000] "HEAD / HTTP/1.1" 405 0 "-" "curl/8.14.1"
192.168.1.163 - - [24/Jun/2026:15:36:40 +0000] "HEAD / HTTP/1.1" 405 0 "-" "curl/8.14.1"
192.168.1.163 - - [24/Jun/2026:15:36:40 +0000] "HEAD /zigbee HTTP/1.1" 404 0 "-" "curl/8.14.1"
172.18.0.1 - - [24/Jun/2026:15:36:59 +0000] "GET / HTTP/1.1" 200 42853 "-" "curl/8.14.1"
192.168.1.163 - - [24/Jun/2026:15:39:22 +0000] "GET / HTTP/1.1" 200 42853 "-" "curl/8.14.1"
172.18.0.1 - - [24/Jun/2026:15:39:24 +0000] "GET / HTTP/1.1" 200 42853 "-" "curl/8.14.1"
172.18.0.1 - - [24/Jun/2026:15:45:05 +0000] "HEAD / HTTP/1.1" 405 0 "-" "curl/8.14.1"

### Reiniciar servicios


### Ver estado de todos los contenedores


## Actualizar IP en DuckDNS

DuckDNS ya tiene tu IP configurada (188.26.212.124). Si tu ISP cambia tu IP pública, necesitarás actualizarla.

### Opción 1: Manual (desde la web)
Ve a https://www.duckdns.org y click en update ip

### Opción 2: Automático con script


## Próximos Pasos (Opcional)

### 1. Añadir HTTPS con Let ' s Encrypt

Para acceso seguro con certificado SSL:
- Instalar Certbot
- Obtener certificado para cuchi-casa.duckdns.org
- Actualizar nginx para escuchar en puerto 443
- Configurar port forwarding para puerto 443

### 2. Añadir Autenticación Básica

Proteger con usuario/contraseña:


### 3. Failover / Backup

- Configurar respaldo automático de /data
- Documentar procedimiento de recuperación

## Troubleshooting

### No puedo acceder desde Internet

1. Verifica que el port forwarding esté configurado
2. Verifica que DuckDNS tenga tu IP correcta
3. Prueba acceso local primero: http://192.168.1.163
4. Revisa logs de nginx: /docker-entrypoint.sh: /docker-entrypoint.d/ is not empty, will attempt to perform configuration
/docker-entrypoint.sh: Looking for shell scripts in /docker-entrypoint.d/
/docker-entrypoint.sh: Launching /docker-entrypoint.d/10-listen-on-ipv6-by-default.sh
10-listen-on-ipv6-by-default.sh: info: Getting the checksum of /etc/nginx/conf.d/default.conf
10-listen-on-ipv6-by-default.sh: info: Enabled listen on IPv6 in /etc/nginx/conf.d/default.conf
/docker-entrypoint.sh: Sourcing /docker-entrypoint.d/15-local-resolvers.envsh
/docker-entrypoint.sh: Launching /docker-entrypoint.d/20-envsubst-on-templates.sh
/docker-entrypoint.sh: Launching /docker-entrypoint.d/30-tune-worker-processes.sh
/docker-entrypoint.sh: Configuration complete; ready for start up

### Error 502 Bad Gateway

El backend no está respondiendo:
CONTAINER ID   IMAGE                       COMMAND                  CREATED          STATUS                  PORTS                                         NAMES
8bb40e1f9f1a   nginx:alpine                "/docker-entrypoint.…"   15 minutes ago   Up Less than a second   0.0.0.0:80->80/tcp, [::]:80->80/tcp           nginx-reverse-proxy
13bf3bb0f580   smart-home-backend          "uvicorn main:app --…"   15 minutes ago   Up 15 minutes           8080/tcp                                      smart-home-backend
f98ade5e3f6f   eclipse-mosquitto:2         "/docker-entrypoint.…"   15 minutes ago   Up 15 minutes           0.0.0.0:1883->1883/tcp, [::]:1883->1883/tcp   mosquitto
98a7146008e1   koenkk/zigbee2mqtt:latest   "docker-entrypoint.s…"   15 minutes ago   Up 15 minutes           8080-8081/tcp                                 0cb404b944a3_zigbee2mqtt
smart-home-backend

### Zigbee2MQTT no carga correctamente

Puede ser un problema de rutas. Intenta acceder con barra final:
http://cuchi-casa.duckdns.org/zigbee/

### DuckDNS no actualiza mi IP

Tu ISP puede estar usando CGNAT. Contacta a tu ISP para obtener una IP pública.

## Archivos de Configuración

- **Nginx config**: 
- **Docker Compose**: 
- **Logs de Nginx**: 

## Recursos

- DuckDNS: https://www.duckdns.org
- Tu dominio: cuchi-casa.duckdns.org
- IP pública actual: 188.26.212.124
- IP local Raspberry: 192.168.1.163

---

**Última actualización**: 
**Estado**: ✅ Nginx configurado, ⚠️ Pendiente port forwarding

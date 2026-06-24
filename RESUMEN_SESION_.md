# Resumen de Sesión - Smart Home Remote Access

**Fecha:** 24 de Junio, 2026

## ✅ Completado en Esta Sesión

### 1. Configuración de Red
- ✅ IP estática configurada: **192.168.1.163**
- ✅ DuckDNS registrado: **cuchi-casa.duckdns.org → 188.26.212.124**
- ✅ Nginx Reverse Proxy implementado
  - Backend (AC): http://raspberrypi/
  - Zigbee2MQTT: http://raspberrypi/zigbee

### 2. Limpieza de Cloudflare
- ✅ Cloudflare Tunnel eliminado (no era viable con DuckDNS subdomain)
- ✅ Imágenes Docker eliminadas para liberar espacio
- ✅ Variables de entorno limpiadas

### 3. Intento de Port Forwarding
- ❌ Configurado en router DIGI pero NO funciona
- 🔍 Diagnóstico: ISP con CGNAT (Carrier-Grade NAT)
- 📝 Port forwarding tradicional NO es posible

### 4. Solución Implementada: Tailscale VPN
- ✅ Tailscale instalado en Raspberry Pi
- ✅ Cuenta conectada: acmlsn@gmail.com
- ✅ IP Tailscale: **100.96.160.24**
- ✅ Acceso funcionando desde cualquier lugar

### 5. Documentación Creada
- ✅ TAILSCALE_SETUP.md - Guía de uso Tailscale
- ✅ SECURITY_TODO.md - Requisitos seguridad (HTTPS + Auth)
- ✅ PUBLIC_URL_TODO.md - Plan para URL pública sin VPN
- ✅ NGINX_SETUP.md - Configuración Nginx reverse proxy
- ✅ Requisito F0.28 añadido - Public URL Access

---

## 🎯 Estado Actual

### Acceso Local (WiFi casa)
`
http://192.168.1.163/        → Backend (AC Control)
http://192.168.1.163/zigbee  → Zigbee2MQTT Config
`

### Acceso Remoto (Tailscale)
`
http://100.96.160.24/        → Backend (AC Control)
http://raspberrypi/          → Backend (nombre DNS)
http://raspberrypi/zigbee    → Zigbee2MQTT Config
`

### Arquitectura Final

`
Internet (desde móvil/PC)
    ↓
Tailscale Network (VPN cifrada)
    ↓
Raspberry Pi (192.168.1.163)
    ↓
Nginx Reverse Proxy (puerto 80)
    ├── / → Backend:8080 (Control AC)
    └── /zigbee → Zigbee2MQTT:8081
`

---

## ⏳ Pendiente para Próximas Sesiones

### Prioridad ALTA

1. **Public URL Access (F0.28)** - Nuevo requisito usuario
   - Opción recomendada: Cloudflare Tunnel
   - Alternativa: Llamar a DIGI para IP pública sin CGNAT
   - Objetivo: http://cuchi-casa.duckdns.org sin VPN

2. **HTTPS + Autenticación (F0.24, F0.25)**
   - Let's Encrypt SSL certificate
   - HTTP Basic Authentication
   - Security headers
   - Documentado en: SECURITY_TODO.md

### Prioridad MEDIA

3. **Rate Limiting (F0.27)**
   - Protección contra brute force
   - Max 10 req/min por IP

4. **MagicDNS en Tailscale**
   - URLs más amigables dentro de VPN

---

## 📊 Servicios en Ejecución

| Servicio | Estado | Puerto | Notas |
|----------|--------|--------|-------|
| mosquitto | ✅ Running | 1883 | MQTT broker |
| zigbee2mqtt | ✅ Running | 8081 | Vía nginx /zigbee |
| smart-home-backend | ✅ Running | 8080 | FastAPI AC control |
| nginx-reverse-proxy | ✅ Running | 80 | Reverse proxy |
| tailscaled | ✅ Running | - | VPN daemon |

---

## 💡 Lecciones Aprendidas

1. **CGNAT es común en España** - Port forwarding no funciona
2. **DuckDNS subdomain no sirve con Cloudflare Tunnel** - Necesita dominio propio
3. **Tailscale es excelente solución temporal** - Rápido y seguro
4. **Nginx reverse proxy unifica acceso** - Un puerto, múltiples servicios

---

## 📞 Próximos Pasos Sugeridos

### Opción A: Usar Tailscale (actual)
- Instalar Tailscale en móvil
- Usar http://raspberrypi para acceder
- **Pros:** Ya funciona, seguro, gratis
- **Contras:** Requiere VPN (deseo de usuario: evitarlo)

### Opción B: Implementar URL pública
1. Llamar a DIGI (1777):  ¿Ofrecéis IP pública sin CGNAT?
2. Si sí → Port forwarding + HTTPS + Auth
3. Si no → Cloudflare Tunnel (requiere dominio ~€10/año)

---

## 📚 Recursos Útiles

- **Tailscale App iOS:** https://apps.apple.com/app/tailscale/id1470499037
- **Tailscale App Android:** https://play.google.com/store/apps/details?id=com.tailscale.ipn
- **Cloudflare:** https://www.cloudflare.com/
- **DuckDNS:** https://www.duckdns.org/
- **Let's Encrypt:** https://letsencrypt.org/

---

**Sesión completada:** 24 Junio 2026, ~18:00 CEST  
**Duración aproximada:** 3 horas  
**Estado:** ✅ Acceso remoto funcionando vía Tailscale  
**Próximo objetivo:** Implementar F0.28 (Public URL sin VPN)

# Nginx Reverse Proxy Setup - Smart Home

## Estado Actual

✅ Nginx configurado y funcionando
✅ Backend (AC) accesible en ruta /
✅ Zigbee2MQTT accesible en ruta /zigbee

## URLs Configuradas

- **Backend (Control AC)**: http://cuchi-casa.duckdns.org/
- **Zigbee2MQTT**: http://cuchi-casa.duckdns.org/zigbee
- **Health Check**: http://cuchi-casa.duckdns.org/health

## Paso Final: Configurar Port Forwarding en el Router

### Configuración Necesaria

Accede a tu router DIGI (http://192.168.1.1) y configura:

**Port Forwarding:**
- Nombre: smart-home
- Puerto externo: 80
- IP interna: 192.168.1.163
- Puerto interno: 80
- Protocolo: TCP

### Verificación

Una vez configurado el port forwarding, prueba desde tu móvil (usando datos, NO WiFi):

http://cuchi-casa.duckdns.org

Deberías ver tu aplicación de control AC.

Para Zigbee2MQTT:

http://cuchi-casa.duckdns.org/zigbee

## Arquitectura

`
Internet
  ↓
Router (188.26.212.124)
  ↓ Port Forward 80:80
Raspberry Pi (192.168.1.163)
  ↓
Nginx Reverse Proxy (puerto 80)
  ├── / → Backend:8080 (Control AC)
  └── /zigbee → Zigbee2MQTT:8081
`

## Comandos Útiles

### Ver logs de Nginx
docker logs nginx-reverse-proxy

### Reiniciar Nginx
docker restart nginx-reverse-proxy

### Ver todos los contenedores
docker ps

### Probar localmente
curl http://localhost/health
curl -I http://localhost/

## Siguiente Paso: HTTPS (Opcional)

Si quieres añadir HTTPS con certificado SSL gratis:
1. Instalar certbot en la Raspberry
2. Obtener certificado para cuchi-casa.duckdns.org
3. Actualizar nginx.conf con SSL
4. Cambiar port forwarding al puerto 443

---

Última actualización: Junio 24, 2026

# Tailscale VPN Setup - Smart Home

## ¿Qué es Tailscale?

Tailscale crea una VPN privada que conecta tus dispositivos de forma segura, sin necesidad de port forwarding ni exposición pública.

## Estado de Instalación

✅ Tailscale instalado en Raspberry Pi
✅ Servicio habilitado y corriendo
⏳ Pendiente: Autenticación (necesitas autorizar el dispositivo)

## Cómo Funciona

\\\
Tu Móvil (con Tailscale) → Internet → Tailscale Network → Raspberry Pi
                                                              ↓
                                                        http://100.x.x.x:8888
\\\

## Acceso a tu Smart Home

Una vez autenticado y con Tailscale instalado en tu móvil:

### Opción 1: IP de Tailscale
\\\
http://100.x.x.x:8888
\\\
(Obtendrás la IP exacta después de autenticar)

### Opción 2: Nombre del dispositivo
\\\
http://raspberrypi:8888
\\\

## Instalación en Otros Dispositivos

### En tu Móvil (iOS/Android)
1. Descarga la app Tailscale desde App Store o Google Play
2. Inicia sesión con la misma cuenta
3. Activa la VPN
4. Accede a http://raspberrypi:8888

### En tu PC Windows
1. Descarga Tailscale: https://tailscale.com/download/windows
2. Instala y inicia sesión
3. Activa la conexión
4. Accede a http://raspberrypi:8888

### En tu Mac
1. Descarga Tailscale: https://tailscale.com/download/mac
2. Instala y inicia sesión
3. Activa la conexión
4. Accede a http://raspberrypi:8888

## Ventajas de Tailscale

✅ **Sin port forwarding** - Funciona con CGNAT
✅ **Cifrado end-to-end** - Más seguro que HTTPS público
✅ **Sin configuración de router** - Todo funciona automáticamente
✅ **Acceso desde cualquier lugar** - Como si estuvieras en casa
✅ **Gratis para uso personal** - Hasta 100 dispositivos
✅ **MagicDNS** - Acceso por nombre en vez de IP

## Comandos Útiles

### Ver estado de Tailscale
\\\ash
sudo tailscale status
\\\

### Ver tu IP de Tailscale
\\\ash
sudo tailscale ip -4
\\\

### Desconectar
\\\ash
sudo tailscale down
\\\

### Reconectar
\\\ash
sudo tailscale up
\\\

## Comparación: Antes vs Después

| Aspecto | Port Forwarding (no funcionó) | Tailscale ✅ |
|---------|-------------------------------|--------------|
| Funciona con CGNAT | ❌ No | ✅ Sí |
| Requiere configurar router | ✅ Sí | ❌ No |
| Cifrado | Solo con HTTPS | ✅ Siempre |
| Autenticación | Manual | ✅ Integrada |
| Exposición pública | ✅ Sí (riesgoso) | ❌ No |
| Funciona en cualquier red | ❌ Depende | ✅ Sí |

## Próximos Pasos

1. ✅ Autenticar Raspberry Pi en https://login.tailscale.com
2. ⏳ Instalar Tailscale en tu móvil
3. ⏳ Conectar y acceder a http://raspberrypi:8888
4. ⏳ [Opcional] Habilitar MagicDNS para nombres más fáciles

---

Creado: Junio 24, 2026
Última actualización: Junio 24, 2026

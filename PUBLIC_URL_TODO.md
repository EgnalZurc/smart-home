# Public URL Access - Implementation Plan

## Objetivo

Acceder a la aplicación smart-home desde una URL pública tipo:
**http://cuchi-casa.duckdns.org** (sin depender de VPN)

## Restricciones Actuales

- ❌ ISP con CGNAT (DIGI Spain)
- ❌ Port forwarding NO funciona
- ❌ No queremos depender de VPN (Tailscale es temporal)

## Soluciones Viables

### 🥇 Opción 1: Cloudflare Tunnel (Recomendada)

**Ventajas:**
- ✅ Funciona con CGNAT
- ✅ Gratis para siempre
- ✅ HTTPS automático
- ✅ Sin port forwarding

**Desventajas:**
- ⚠️ Necesita dominio registrado en Cloudflare
- ⚠️ DuckDNS subdomain no sirve directamente

**Pasos:**
1. Registrar dominio barato (~€5-10/año) en Cloudflare
2. O usar worker de Cloudflare con subdominio .workers.dev
3. Configurar tunnel (ya parcialmente hecho antes)
4. Añadir autenticación HTTP Basic
5. Configurar HTTPS

**Costo:** €0 (o €5-10/año si compras dominio)

---

### 🥈 Opción 2: VPS + Reverse SSH Tunnel

**Ventajas:**
- ✅ Control total
- ✅ Funciona con CGNAT
- ✅ Puedes usar DuckDNS

**Desventajas:**
- ⚠️ Costo mensual (~€3-5/mes)
- ⚠️ Más complejo de mantener

**Pasos:**
1. Contratar VPS barato (Hetzner, Contabo, etc.)
2. Configurar autossh desde Raspberry → VPS
3. Nginx en VPS forward a tunnel
4. DuckDNS apunta a IP del VPS

**Costo:** €3-5/mes

---

### 🥉 Opción 3: Pedir IP Pública Real a DIGI

**Ventajas:**
- ✅ Port forwarding tradicional funciona
- ✅ Sin dependencias externas
- ✅ Puedes usar DuckDNS

**Desventajas:**
- ⚠️ Puede costar extra
- ⚠️ No todos los ISPs lo ofrecen

**Pasos:**
1. Llamar a DIGI: 1777 (atención cliente)
2. Solicitar:  IP pública fija sin CGNAT
3. Preguntar costo (puede ser gratis o ~€5/mes)
4. Una vez asignada, configurar port forwarding
5. Implementar HTTPS + Auth

**Costo:** €0-5/mes (según DIGI)

---

## 📊 Comparación

| Aspecto | Cloudflare Tunnel | VPS + Tunnel | IP Pública DIGI |
|---------|-------------------|--------------|-----------------|
| **Costo** | Gratis | €3-5/mes | €0-5/mes |
| **Complejidad** | Media | Alta | Baja |
| **Control** | Medio | Alto | Alto |
| **Mantenimiento** | Bajo | Medio | Bajo |
| **Fiabilidad** | Alta | Media | Alta |
| **Usa DuckDNS** | ❌ No | ✅ Sí | ✅ Sí |

---

## 🎯 Recomendación

**1. Corto plazo (ahora):**
- Usar Tailscale VPN (ya funciona)

**2. Medio plazo (próxima sesión):**
- Llamar a DIGI y preguntar por IP pública
- Si es gratis/barato → Opción 3
- Si no → Opción 1 (Cloudflare Tunnel)

**3. Largo plazo:**
- Mantener la solución que funcione mejor

---

## 📞 Script para Llamar a DIGI

**Teléfono:** 1777 (atención al cliente)

**Qué decir:**
> Buenos días soy cliente de fibra de DIGI. Necesito una IP pública real

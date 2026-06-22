# 📘 Guía Paso a Paso - Publicar en GitHub

Esta guía te ayudará a publicar tu proyecto Smart Home en GitHub desde cero.

---

## 📋 Pre-requisitos

- [ ] Cuenta de GitHub creada (https://github.com)
- [ ] Git instalado en Windows
- [ ] Proyecto en `E:\Projects\smart-home`

---

## 🚀 Paso 1: Instalar Git (si no lo tienes)

### Opción A: Git para Windows

1. Descargar de https://git-scm.com/download/win
2. Instalar con opciones por defecto
3. Verificar instalación:
   ```cmd
   git --version
   ```

### Opción B: Git con GitHub Desktop (más fácil)

1. Descargar GitHub Desktop: https://desktop.github.com
2. Instalar y hacer login con tu cuenta GitHub
3. Git se instala automáticamente

---

## 🌐 Paso 2: Crear Repositorio en GitHub

1. **Ir a GitHub:** https://github.com/new

2. **Configurar repositorio:**
   - **Repository name:** `smart-home`
   - **Description:** `Sistema de domótica modular con control inteligente de AC y tracking de energía`
   - **Visibility:** Público ✅ (o Privado si prefieres)
   - **NO marcar** "Initialize this repository with:"
     - ❌ Add a README file
     - ❌ Add .gitignore
     - ❌ Choose a license
   
   > Ya tenemos estos archivos localmente

3. **Crear repositorio** (botón verde)

4. **Copiar URL del repositorio** que aparece
   - Ejemplo: `https://github.com/EgnalZurc/smart-home.git`

---

## 💻 Paso 3: Configurar Git Local

### Abrir PowerShell o CMD en el directorio del proyecto

```powershell
# Navegar al proyecto
cd E:\Projects\smart-home
```

### Configurar tu identidad en Git (primera vez)

```powershell
git config --global user.name "Egnal Zurc"
git config --global user.email "tu_email@ejemplo.com"
```

> Usa el mismo email de tu cuenta GitHub

---

## 📦 Paso 4: Inicializar Repositorio Local

```powershell
# Inicializar Git (si no está ya)
git init

# Verificar que se creó la carpeta .git
dir -Force
```

Deberías ver una carpeta `.git` (oculta).

---

## 🔐 Paso 5: VERIFICACIÓN CRÍTICA - Archivos Sensibles

**⚠️ MUY IMPORTANTE: Verificar que `.env` NO se va a subir**

```powershell
# Ver estado actual
git status
```

**Revisar la salida:**
- ✅ `.env.example` debe aparecer (OK para subir)
- ❌ `.env` NO debe aparecer (si aparece, PARA y revisa .gitignore)

**Si `.env` aparece listado:**

```powershell
# Verificar que está en .gitignore
type .gitignore | findstr .env

# Debería mostrar:
# .env

# Si no aparece, añadirlo:
echo .env >> .gitignore
```

---

## 📝 Paso 6: Añadir Archivos al Repositorio

```powershell
# Añadir todos los archivos (respeta .gitignore)
git add .

# Ver qué se va a commitear
git status
```

**Verificar lista de archivos:**
- ✅ Debe aparecer: README.md, src/, docs/, docker-compose.yml, etc.
- ❌ NO debe aparecer: .env, src/backend/data/*.json

---

## 💾 Paso 7: Primer Commit

```powershell
git commit -m "Initial commit - Fase 0 completa

- Control inteligente AC con 5 sensores Zigbee
- Tracking de energía con ESIOS API
- Web UI responsive con Chart.js
- 29/30 requerimientos implementados
- Docker + Docker Compose listo para Raspberry Pi
"
```

**Salida esperada:**
```
[main (root-commit) abc1234] Initial commit - Fase 0 completa
 XX files changed, XXXX insertions(+)
 create mode 100644 README.md
 ...
```

---

## 🌿 Paso 8: Configurar Rama Principal

```powershell
# Renombrar rama a 'main' (estándar de GitHub)
git branch -M main
```

---

## 🔗 Paso 9: Conectar con GitHub

```powershell
# Añadir remote (reemplaza con tu URL de GitHub)
git remote add origin https://github.com/EgnalZurc/smart-home.git

# Verificar que se añadió correctamente
git remote -v
```

**Salida esperada:**
```
origin  https://github.com/EgnalZurc/smart-home.git (fetch)
origin  https://github.com/EgnalZurc/smart-home.git (push)
```

---

## 🚀 Paso 10: Publicar en GitHub

```powershell
# Push (primera vez con -u para tracking)
git push -u origin main
```

**GitHub te pedirá autenticación:**

### Opción A: Personal Access Token (Recomendado)

1. GitHub bloquea contraseñas simples desde 2021
2. Necesitas crear un Personal Access Token:
   - Ir a: https://github.com/settings/tokens
   - "Generate new token (classic)"
   - **Note:** `smart-home-token`
   - **Expiration:** 90 days (o lo que prefieras)
   - **Scopes:** Marcar `repo` (acceso completo)
   - Generar token
   - **Copiar token** (solo se muestra una vez)

3. Al hacer `git push`, usar:
   - **Username:** `EgnalZurc`
   - **Password:** (pegar el token, no tu contraseña)

### Opción B: GitHub Desktop (Más fácil)

Si usaste GitHub Desktop, la autenticación es automática.

---

## ✅ Paso 11: Verificar en GitHub

1. **Abrir navegador:** https://github.com/EgnalZurc/smart-home

2. **Verificar que se ve:**
   - ✅ README.md renderizado con badges
   - ✅ Estructura de carpetas correcta
   - ✅ LICENSE visible
   - ✅ Archivos de documentación

3. **Verificar que NO se ve:**
   - ❌ `.env` (credenciales)
   - ❌ Archivos de datos sensibles

---

## 🎉 ¡Listo! Repositorio Publicado

Tu proyecto ya está en GitHub. Ahora puedes:

### Clonar en Raspberry Pi

```bash
# En la Raspberry Pi
cd ~
git clone https://github.com/EgnalZurc/smart-home.git
cd smart-home
cp .env.example .env
nano .env  # Configurar credenciales
docker-compose up -d --build
```

---

## 🔄 Actualizaciones Futuras

### Cuando hagas cambios en el código:

```powershell
# Ver archivos modificados
git status

# Añadir cambios
git add .

# Commit con mensaje descriptivo
git commit -m "Descripción del cambio"

# Push a GitHub
git push
```

### Para actualizar en la Raspberry Pi:

```bash
cd ~/smart-home
git pull
docker-compose down
docker-compose up -d --build
```

---

## 🐛 Solución de Problemas

### Error: "remote origin already exists"

```powershell
git remote remove origin
git remote add origin https://github.com/EgnalZurc/smart-home.git
```

### Error: "Your branch is ahead of 'origin/main'"

```powershell
git push
```

### Error: "Authentication failed"

Necesitas crear Personal Access Token (ver Paso 10, Opción A).

### Cometiste error y subiste .env

```powershell
# Eliminar del historial
git rm --cached .env
git commit -m "Remove .env from repository"
git push

# IMPORTANTE: Rotar credenciales MELCloud inmediatamente
# (cambiar contraseña en la app MELCloud)
```

---

## 📖 Recursos Adicionales

### Git Básico

```powershell
# Ver historial
git log --oneline

# Ver cambios
git diff

# Crear rama
git checkout -b feature/nueva-funcionalidad

# Cambiar de rama
git checkout main

# Ver ramas
git branch
```

### GitHub

- **Issues:** Para reportar bugs o sugerir features
- **Pull Requests:** Para contribuciones
- **Releases:** Para versiones estables
- **Wiki:** Documentación adicional

---

## ✅ Checklist Final

- [ ] Git instalado y configurado
- [ ] Repositorio creado en GitHub
- [ ] `.env` NO se subió (verificado en GitHub)
- [ ] README se ve correctamente
- [ ] Todos los archivos necesarios están
- [ ] Proyecto accesible desde la URL de GitHub

---

## 🎯 Próximos Pasos

1. **Probar despliegue** en Raspberry Pi siguiendo [DEPLOY.md](DEPLOY.md)
2. **Compartir proyecto** (opcional):
   - Reddit r/homeautomation
   - Home Assistant community
3. **Implementar Fase 1** (Control de Humedad)

---

**¿Necesitas ayuda?** Revisa la sección "Solución de Problemas" o crea un Issue en GitHub.

---

**Fecha:** 22 de junio de 2026  
**Versión:** 1.0

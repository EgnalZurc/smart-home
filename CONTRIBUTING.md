# Contributing to Smart Home Control

¡Gracias por tu interés en contribuir! Este documento explica cómo colaborar en el proyecto.

---

## 🌟 Formas de Contribuir

- 🐛 Reportar bugs
- 💡 Sugerir nuevas funcionalidades
- 📝 Mejorar documentación
- 🔧 Enviar código (pull requests)
- 🧪 Probar en diferentes entornos
- 🌍 Traducir documentación

---

## 🐛 Reportar Bugs

### Antes de reportar

1. Buscar en [Issues](https://github.com/EgnalZurc/smart-home/issues) existentes
2. Probar con la última versión del código
3. Verificar que el problema es reproducible

### Crear Issue

Incluir:
- **Descripción clara** del problema
- **Pasos para reproducir** (1, 2, 3...)
- **Comportamiento esperado** vs **comportamiento actual**
- **Logs relevantes** (usar `docker-compose logs`)
- **Entorno**: SO, versión Docker, modelo Raspberry Pi
- **Capturas de pantalla** (si aplica)

---

## 💡 Sugerir Funcionalidades

### Proponer nueva feature

1. Abrir [Issue](https://github.com/EgnalZurc/smart-home/issues/new) con etiqueta `enhancement`
2. Describir:
   - ¿Qué problema resuelve?
   - ¿Cómo funcionaría?
   - ¿Afecta a hardware existente o requiere nuevo hardware?
   - ¿Encaja en alguna fase existente o requiere nueva fase?

### Proponer nueva fase

Ver [README.md - Añadir nuevas fases](README.md#añadir-nuevas-fases)

1. Crear documento `docs/faseN-nombre.md`
2. Definir requerimientos (F{N}.1, F{N}.2, ...)
3. Especificar hardware adicional
4. Diseñar lógica/arquitectura
5. Abrir Pull Request con la propuesta

---

## 🔧 Contribuir Código

### Setup de Desarrollo

```bash
# Fork del repositorio en GitHub

# Clonar tu fork
git clone https://github.com/TU_USUARIO/smart-home.git
cd smart-home

# Añadir upstream
git remote add upstream https://github.com/EgnalZurc/smart-home.git

# Crear rama para tu feature
git checkout -b feature/nombre-descriptivo
```

### Desarrollo Local

```bash
# Usar docker-compose.dev.yml para desarrollo
docker-compose -f docker-compose.dev.yml up -d --build

# Ver logs
docker-compose -f docker-compose.dev.yml logs -f

# Reiniciar backend tras cambios
docker restart smart-home-backend
```

### Antes de Commit

```bash
# Verificar que no hay credenciales
git status
git diff

# Verificar que .env NO está staged
git status | grep .env

# Verificar Python (si modificaste backend)
cd src/backend
python -m pytest  # Si hay tests

# Verificar que no rompes nada
docker-compose up -d --build
curl http://localhost:8080/api/status
```

### Commit y Push

```bash
# Commits descriptivos
git add .
git commit -m "feat: Descripción clara de la feature"

# Push a tu fork
git push origin feature/nombre-descriptivo
```

### Pull Request

1. Ir a tu fork en GitHub
2. Click "Compare & pull request"
3. Rellenar template:
   - **Descripción**: ¿Qué hace tu PR?
   - **Issue relacionado**: Fixes #123
   - **Tests**: ¿Cómo lo probaste?
   - **Checklist**: Marcar items completados

---

## 📝 Estilo de Código

### Python (Backend)

- **PEP 8** (style guide estándar)
- **Type hints** cuando sea posible
- **Docstrings** para funciones públicas
- **Logs** con niveles apropiados (INFO, WARNING, ERROR)

```python
async def get_sensor_reading(sensor_id: str) -> dict | None:
    """Obtiene la última lectura de un sensor.
    
    Args:
        sensor_id: ID único del sensor Zigbee
        
    Returns:
        Dict con temperatura, humedad, batería y timestamp.
        None si el sensor no existe.
    """
    # Implementación
```

### JavaScript (Frontend)

- **ES6+** modern syntax
- **camelCase** para variables y funciones
- **Comentarios** en partes complejas
- **Async/await** para promesas

```javascript
async function updateSensorData() {
    try {
        const response = await fetch('/api/sensors');
        const data = await response.json();
        renderSensors(data);
    } catch (error) {
        console.error('Error fetching sensors:', error);
    }
}
```

### Commits

Seguir [Conventional Commits](https://www.conventionalcommits.org/):

```
feat: Añadir soporte para sensores de movimiento
fix: Corregir cálculo de temperatura media
docs: Actualizar guía de despliegue
refactor: Simplificar lógica del controlador AC
test: Añadir tests para state machine
chore: Actualizar dependencias
```

---

## 🧪 Tests

### Ejecutar Tests

```bash
cd src/backend
python -m pytest
python -m pytest tests/test_state_machine.py -v
```

### Añadir Tests

- Tests unitarios para lógica de negocio
- Tests de integración para API endpoints
- Tests en `src/backend/tests/`

```python
def test_temperature_average():
    """Test cálculo de temperatura media"""
    sensors = [
        {'temperature': 25.0},
        {'temperature': 26.0},
        {'temperature': 24.0},
    ]
    assert calculate_average(sensors) == 25.0
```

---

## 📚 Documentación

### Actualizar Documentación

Si tu PR afecta:
- **Funcionalidad**: Actualizar README.md
- **Despliegue**: Actualizar DEPLOY.md
- **Uso**: Actualizar QUICKSTART.md
- **Arquitectura**: Actualizar docs/ correspondiente

### Crear Nueva Documentación

- Markdown con formato consistente
- Ejemplos de código cuando sea relevante
- Screenshots si ayudan a entender
- Links a documentación externa

---

## 🔐 Seguridad

### Reportar Vulnerabilidad

**NO** abrir issue público. Enviar email privado a:
- **Email**: [acmlsn@gmail.com](mailto:acmlsn@gmail.com)
- **Asunto**: `[SECURITY] Descripción breve`

Incluir:
- Descripción de la vulnerabilidad
- Pasos para reproducir
- Impacto potencial
- Posible solución (si la conoces)

### Buenas Prácticas

- ❌ **NUNCA** commitear credenciales (`.env`, passwords, API keys)
- ✅ Usar `.env.example` para plantillas
- ✅ Verificar `.gitignore` antes de commit
- ✅ Usar secrets de GitHub Actions para CI/CD

---

## 📦 Releases

### Versionado

Seguir [Semantic Versioning](https://semver.org/):
- `MAJOR.MINOR.PATCH` (ej: `1.2.3`)
- **MAJOR**: Cambios incompatibles
- **MINOR**: Nueva funcionalidad compatible
- **PATCH**: Bug fixes compatibles

### Crear Release

1. Actualizar `CHANGELOG.md` (si existe)
2. Tag en Git: `git tag v1.2.0`
3. Push tag: `git push origin v1.2.0`
4. GitHub Actions construye imagen Docker automáticamente
5. Crear release en GitHub con notas

---

## 🤝 Código de Conducta

### Nuestro Compromiso

- 🤗 Entorno acogedor e inclusivo
- 🎯 Enfoque en lo que es mejor para la comunidad
- 😊 Respeto y empatía hacia otros colaboradores
- 🙏 Aceptar críticas constructivas
- 🌍 Diversidad de experiencias y perspectivas

### Comportamiento Esperado

- ✅ Lenguaje acogedor e inclusivo
- ✅ Respetar puntos de vista diferentes
- ✅ Aceptar críticas constructivas
- ✅ Enfocarse en lo mejor para la comunidad

### Comportamiento Inaceptable

- ❌ Lenguaje ofensivo o inapropiado
- ❌ Trolling o comentarios despectivos
- ❌ Acoso público o privado
- ❌ Publicar información privada de otros

---

## 📧 Contacto

- **Issues**: [GitHub Issues](https://github.com/EgnalZurc/smart-home/issues)
- **Email**: acmlsn@gmail.com
- **Twitter**: _Próximamente_

---

## ⭐ Reconocimientos

Todos los contribuidores serán reconocidos en:
- README.md (sección Contributors)
- CHANGELOG.md (por release)
- GitHub contributors page

---

## 📄 Licencia

Al contribuir, aceptas que tus contribuciones se licenciarán bajo la [MIT License](LICENSE).

---

**¡Gracias por contribuir!** 🎉

Tu ayuda hace que este proyecto sea mejor para todos.

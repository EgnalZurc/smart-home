# Internationalization (i18n) Implementation Plan

**Status**: 📋 Planning Phase  
**Priority**: HIGH  
**Impact**: All project files (code, docs, frontend)  
**Estimated effort**: 12-16 hours

---

## 🎯 OBJECTIVE

Transform the Smart Home project to use **English as the primary language** for:
- All source code (variables, functions, classes, comments)
- All documentation (README, guides, technical docs)
- All log messages and system outputs
- Frontend UI with multi-language support

---

## 📊 CURRENT STATE ANALYSIS

### Backend Code (Spanish → English)

#### Files requiring refactoring:
1. `src/backend/main.py` - Variable names, comments, log messages
2. `src/backend/mqtt_handler.py` - Class/method names, docstrings
3. `src/backend/melcloud_client.py` - Comments, logs
4. `src/backend/cleanup.py` - Function names, logs
5. `src/backend/zigbee2mqtt_client.py` - Docstrings, logs
6. `src/backend/controllers/ac_controller.py` - Variable names, logs
7. `src/backend/controllers/state_machine.py` - State names, comments
8. `src/backend/api/routes.py` - Endpoint docs, error messages

**Estimated changes**:
- ~150 variable/function renames
- ~200 log message translations
- ~100 comment translations
- ~50 docstring translations

### Documentation (Spanish → English)

#### Files requiring translation:
1. `README.md` - Complete translation
2. `REQUIREMENTS.md` - Complete translation
3. `ANALISIS_CODIGO.md` - Complete translation
4. `CHANGELOG_REFACTOR.md` - Complete translation
5. `DEPLOYMENT_SUCCESS.md` - Complete translation
6. `CONTRIBUTING.md` - Complete translation (if exists)
7. `QUICKSTART.md` - Complete translation (if exists)
8. `DEPLOY.md` - Complete translation (if exists)

**Estimated pages**: ~40-50 pages of markdown content

### Frontend (No multi-language support)

Current state:
- ❌ All texts hardcoded in Spanish in HTML
- ❌ No translation system
- ❌ No language selector
- ❌ No locale persistence

---

## 🗺️ IMPLEMENTATION PHASES

### Phase 1: Backend Code Refactoring (4-6 hours)

**Goal**: Translate all Python code to English

#### Step 1.1: Rename Variables and Functions
```python
# BEFORE (Spanish)
sensor_nombres = ["Despacho", "Habitación Papis"]
temperatura_objetivo = 26.0
def obtener_sensores_activos():
    pass

# AFTER (English)
sensor_names = ["Office", "Parents Bedroom"]
target_temperature = 26.0
def get_active_sensors():
    pass
```

**Strategy**:
- Use IDE refactoring tools for safe renames
- Keep Spanish sensor friendly names (user-defined)
- Update all docstrings to English
- Maintain semantic equivalence

#### Step 1.2: Translate Log Messages
```python
# BEFORE
logger.info("Sensores descubiertos: %s", sensor_names)
logger.error("No se pudo conectar a MQTT")

# AFTER
logger.info("Sensors discovered: %s", sensor_names)
logger.error("Failed to connect to MQTT")
```

#### Step 1.3: Translate Comments
```python
# BEFORE
# Ciclo principal de control: leer → evaluar → aplicar → registrar

# AFTER
# Main control loop: read → evaluate → apply → record
```

**Files priority**:
1. High: `main.py`, `ac_controller.py`, `state_machine.py`
2. Medium: `mqtt_handler.py`, `melcloud_client.py`, `routes.py`
3. Low: `cleanup.py`, `zigbee2mqtt_client.py`

---

### Phase 2: Documentation Translation (4-6 hours)

**Goal**: Translate all markdown documentation to English

#### Step 2.1: Core Documentation
Priority order:
1. `README.md` - Project overview and setup
2. `REQUIREMENTS.md` - Requirements list
3. `QUICKSTART.md` - Quick start guide
4. `CONTRIBUTING.md` - Contribution guidelines

#### Step 2.2: Technical Documentation
5. `ANALISIS_CODIGO.md` → `CODE_ANALYSIS.md`
6. `CHANGELOG_REFACTOR.md` → Keep name, translate content
7. `DEPLOYMENT_SUCCESS.md` → Keep name, translate content
8. `DEPLOY.md` - Deployment guide

#### Step 2.3: Rename Spanish-named Files
- Rename files with Spanish names to English equivalents
- Update all references in other documents
- Update git history if needed

**Translation guidelines**:
- Keep technical terms in English (MQTT, Docker, API)
- Translate UI/UX related content
- Maintain code examples as-is (bilingual comments OK)
- Keep proper names unchanged (Valdebernardo, Madrid)

---

### Phase 3: Frontend i18n System (2-3 hours)

**Goal**: Implement multi-language support in web UI

#### Step 3.1: Choose i18n Approach

**Option A: Vanilla JS (Recommended)**
- No dependencies
- Lightweight (~100 lines of code)
- Full control
- Easy to maintain

**Option B: Library (i18next)**
- More features
- Well-tested
- Larger footprint
- Requires npm/build

**Decision**: Use Option A (vanilla JS) to maintain simplicity

#### Step 3.2: Create Translation System

Structure:
```
src/backend/static/
├── index.html           (updated with data-i18n attributes)
├── i18n.js             (translation engine)
└── locales/
    ├── en.json         (English translations)
    └── es.json         (Spanish translations)
```

**i18n.js** (translation engine):
```javascript
class I18n {
    constructor(defaultLocale = 'en') {
        this.locale = localStorage.getItem('locale') || defaultLocale;
        this.translations = {};
    }
    
    async loadLocale(locale) {
        const response = await fetch(`/static/locales/${locale}.json`);
        this.translations = await response.json();
        this.locale = locale;
        localStorage.setItem('locale', locale);
    }
    
    t(key) {
        return this.translations[key] || key;
    }
    
    setLocale(locale) {
        this.loadLocale(locale).then(() => this.updateUI());
    }
    
    updateUI() {
        document.querySelectorAll('[data-i18n]').forEach(el => {
            const key = el.getAttribute('data-i18n');
            el.textContent = this.t(key);
        });
    }
}
```

#### Step 3.3: Extract Translatable Strings

Current UI texts to translate (~50-60 strings):
- Page title and headers
- Button labels (Force ON, Force OFF, Auto, etc.)
- Section titles (Sensors, History, Control, etc.)
- Status messages
- Tooltips
- Error messages
- Chart labels

#### Step 3.4: Add Language Selector

UI component:
```html
<div class="language-selector">
    <button onclick="i18n.setLocale('en')" 
            class="lang-btn" 
            data-lang="en">
        🇬🇧 EN
    </button>
    <button onclick="i18n.setLocale('es')" 
            class="lang-btn" 
            data-lang="es">
        🇪🇸 ES
    </button>
</div>
```

---

### Phase 4: API i18n Support (1-2 hours)

**Goal**: Return localized error messages and responses

#### Step 4.1: Add Locale Detection

```python
# routes.py
from fastapi import Request

def get_locale(request: Request) -> str:
    """Extract locale from Accept-Language header."""
    accept_lang = request.headers.get('Accept-Language', 'en')
    # Parse and return best match (en, es)
    return accept_lang.split(',')[0][:2]
```

#### Step 4.2: Create Translation Dictionaries

```python
# translations.py
TRANSLATIONS = {
    'en': {
        'error.temperature_range': 'Temperature must be between {min}°C and {max}°C',
        'error.invalid_mode': 'Mode must be one of: {modes}',
        'success.config_updated': 'Configuration updated successfully',
    },
    'es': {
        'error.temperature_range': 'La temperatura debe estar entre {min}°C y {max}°C',
        'error.invalid_mode': 'El modo debe ser uno de: {modes}',
        'success.config_updated': 'Configuración actualizada correctamente',
    }
}

def t(key: str, locale: str = 'en', **kwargs) -> str:
    """Translate a key with optional parameters."""
    text = TRANSLATIONS.get(locale, {}).get(key, key)
    return text.format(**kwargs) if kwargs else text
```

#### Step 4.3: Update Error Responses

```python
# BEFORE
raise HTTPException(400, "Temperatura debe estar entre 19°C y 30°C")

# AFTER
locale = get_locale(request)
raise HTTPException(
    400, 
    t('error.temperature_range', locale, min=19, max=30)
)
```

---

## 📋 IMPLEMENTATION CHECKLIST

### Phase 1: Backend Code ⏳
- [ ] Rename all variables/functions in `main.py`
- [ ] Rename all variables/functions in `mqtt_handler.py`
- [ ] Rename all variables/functions in `melcloud_client.py`
- [ ] Rename all variables/functions in `cleanup.py`
- [ ] Rename all variables/functions in `zigbee2mqtt_client.py`
- [ ] Rename all variables/functions in `ac_controller.py`
- [ ] Rename all variables/functions in `state_machine.py`
- [ ] Rename all variables/functions in `routes.py`
- [ ] Translate all log messages
- [ ] Translate all docstrings
- [ ] Translate all comments
- [ ] Update tests (if any)

### Phase 2: Documentation ⏳
- [ ] Translate `README.md`
- [ ] Translate `REQUIREMENTS.md`
- [ ] Translate `ANALISIS_CODIGO.md` → `CODE_ANALYSIS.md`
- [ ] Translate `CHANGELOG_REFACTOR.md`
- [ ] Translate `DEPLOYMENT_SUCCESS.md`
- [ ] Translate `QUICKSTART.md`
- [ ] Translate `CONTRIBUTING.md`
- [ ] Translate `DEPLOY.md`
- [ ] Update all internal links
- [ ] Update README badges/links

### Phase 3: Frontend i18n ⏳
- [ ] Create `i18n.js` translation engine
- [ ] Create `locales/en.json` with English translations
- [ ] Create `locales/es.json` with Spanish translations
- [ ] Add `data-i18n` attributes to all UI elements
- [ ] Create language selector component
- [ ] Implement locale persistence (localStorage)
- [ ] Update Chart.js labels with translations
- [ ] Add language indicator in UI
- [ ] Test with both languages
- [ ] Add RTL support (future: Arabic, Hebrew)

### Phase 4: API i18n ⏳
- [ ] Create `translations.py` module
- [ ] Add locale detection from headers
- [ ] Translate all error messages
- [ ] Translate all success messages
- [ ] Update HTTPException calls with t() function
- [ ] Add locale parameter to relevant endpoints
- [ ] Document i18n in API docs
- [ ] Test API with different locales

### Phase 5: Testing & QA ⏳
- [ ] Test backend with English logs
- [ ] Test frontend language switching
- [ ] Test API error messages in both languages
- [ ] Verify all documentation renders correctly
- [ ] Check for untranslated strings
- [ ] Test localStorage persistence
- [ ] Verify browser language detection
- [ ] Cross-browser testing (Chrome, Firefox, Safari)

---

## 🚨 BREAKING CHANGES

### For Developers
- All variable/function names changed (use IDE refactoring)
- All docstrings in English (update IDE autocomplete)
- Log messages in English (update log parsing scripts if any)

### For Users
- No breaking changes (backward compatible)
- UI defaults to English (can switch to Spanish)
- API accepts `Accept-Language` header (optional)

### For Documentation
- All docs in English (Spanish docs can be in `/docs/es/` folder)

---

## 📦 DELIVERABLES

1. **Refactored Python code** - All English
2. **Translated documentation** - All markdown files
3. **i18n system** - Frontend translation engine
4. **Translation files** - JSON locales (en, es)
5. **API i18n support** - Localized error messages
6. **Language selector** - UI component
7. **Updated README** - With i18n instructions
8. **Migration guide** - For contributors

---

## 🎓 BEST PRACTICES

### Code Style
- Use clear, descriptive English names
- Avoid abbreviations unless standard (temp → temperature)
- Follow PEP 8 naming conventions
- Maintain semantic clarity

### Translation Keys
- Use dot notation: `error.temperature_range`
- Prefix by category: `error.`, `success.`, `label.`, `button.`
- Keep keys descriptive: `sensor.temperature` not `sens.temp`

### Documentation
- Write for international audience
- Avoid idioms and slang
- Use simple, clear English
- Include examples and code snippets

### Testing
- Test with both languages
- Verify special characters (°C, %, etc.)
- Check plural forms
- Verify date/time formatting

---

## 📅 ESTIMATED TIMELINE

| Phase | Duration | Dependencies |
|-------|----------|--------------|
| Phase 1: Backend | 4-6 hours | None |
| Phase 2: Documentation | 4-6 hours | None (can run parallel) |
| Phase 3: Frontend i18n | 2-3 hours | Phase 1 complete |
| Phase 4: API i18n | 1-2 hours | Phase 1 complete |
| Phase 5: Testing | 1-2 hours | All phases complete |
| **TOTAL** | **12-19 hours** | - |

**Recommended**: Split over 2-3 days for quality review

---

## 🔄 MAINTENANCE

### Adding New Languages
1. Create `/locales/{lang}.json` with translations
2. Add language button to selector
3. Update documentation
4. Test thoroughly

### Updating Translations
1. Add new keys to all locale files
2. Mark missing translations with `TODO`
3. Request translations from community
4. Update and deploy

### Translation Workflow
1. Developer adds English key
2. Mark for translation in other locales
3. Community/translator provides translations
4. Review and merge

---

## 📚 RESOURCES

### Translation Tools
- [DeepL](https://www.deepl.com/) - High-quality translations
- [Google Translate](https://translate.google.com/) - Quick translations
- [Grammarly](https://www.grammarly.com/) - English grammar check

### i18n Libraries (if needed)
- [i18next](https://www.i18next.com/) - Full-featured i18n framework
- [Format.js](https://formatjs.io/) - Internationalization library

### Documentation
- [FastAPI i18n](https://fastapi.tiangolo.com/advanced/response-headers/) - API headers
- [MDN Web Docs](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Intl) - JavaScript Intl API

---

**Status**: Ready for implementation  
**Next step**: Begin Phase 1 (Backend Code Refactoring)  
**Document owner**: Smart Home Project Team

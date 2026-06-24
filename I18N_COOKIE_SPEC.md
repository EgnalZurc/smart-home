# Cookie-Based Language Persistence Specification

**Feature**: Language preference persistence using browser cookies  
**Priority**: HIGH  
**Status**: Specified

---

## 🎯 REQUIREMENT

User language preference must be stored in **cookies** (not localStorage) with the following behavior:

### First Visit
1. App loads in **English** by default
2. No cookie is present yet
3. User sees English UI

### Language Change
1. User clicks language selector (🇬🇧 EN / 🇪🇸 ES)
2. Language changes immediately (no page reload)
3. Selected language saved to cookie with **365 days** expiration

### Subsequent Visits
1. App reads language preference from cookie
2. If cookie exists → Load saved language
3. If cookie expired or deleted → Load English (default)

---

## 🍪 COOKIE SPECIFICATION

### Cookie Name
```
locale
```

### Cookie Values
```javascript
'en'  // English (default)
'es'  // Spanish
```

### Cookie Attributes

| Attribute | Value | Reason |
|-----------|-------|--------|
| **Name** | `locale` | Simple, descriptive |
| **Value** | `en` or `es` | ISO language codes |
| **Expires** | 365 days (1 year) | Long-term preference |
| **Path** | `/` | Available to entire app |
| **SameSite** | `Strict` | Security (CSRF protection) |
| **Secure** | `false` (dev), `true` (prod) | HTTPS in production |
| **HttpOnly** | `false` | JavaScript needs read access |

### Cookie Format
```
locale=en; expires=Wed, 24 Jun 2027 07:00:00 GMT; path=/; SameSite=Strict
```

---

## 💻 IMPLEMENTATION

### JavaScript Code

```javascript
class I18n {
    constructor(defaultLocale = 'en') {
        // Priority: cookie > default
        this.locale = this.getLocaleFromCookie() || defaultLocale;
        this.translations = {};
    }
    
    /**
     * Read locale preference from cookie
     * @returns {string|null} 'en', 'es', or null if not found
     */
    getLocaleFromCookie() {
        const name = 'locale=';
        const decodedCookie = decodeURIComponent(document.cookie);
        const cookieArray = decodedCookie.split(';');
        
        for (let i = 0; i < cookieArray.length; i++) {
            let cookie = cookieArray[i].trim();
            if (cookie.indexOf(name) === 0) {
                return cookie.substring(name.length, cookie.length);
            }
        }
        return null;  // Cookie not found
    }
    
    /**
     * Save locale preference to cookie (365 days expiration)
     * @param {string} locale - Language code ('en' or 'es')
     */
    setLocaleCookie(locale) {
        const d = new Date();
        d.setTime(d.getTime() + (365 * 24 * 60 * 60 * 1000));  // 365 days
        const expires = "expires=" + d.toUTCString();
        
        // Cookie attributes
        const cookieString = `locale=${locale};${expires};path=/;SameSite=Strict`;
        document.cookie = cookieString;
        
        console.log(`Language preference saved: ${locale} (expires in 365 days)`);
    }
    
    /**
     * Load translations for a locale
     * @param {string} locale - Language code ('en' or 'es')
     */
    async loadLocale(locale) {
        try {
            const response = await fetch(`/static/locales/${locale}.json`);
            if (!response.ok) {
                throw new Error(`Failed to load locale: ${locale}`);
            }
            
            this.translations = await response.json();
            this.locale = locale;
            this.setLocaleCookie(locale);  // Save to cookie
            
            console.log(`Locale loaded: ${locale}`);
        } catch (error) {
            console.error(`Error loading locale ${locale}:`, error);
            // Fallback to English if loading fails
            if (locale !== 'en') {
                console.log('Falling back to English');
                this.loadLocale('en');
            }
        }
    }
    
    /**
     * Change language and update UI
     * @param {string} locale - Language code ('en' or 'es')
     */
    setLocale(locale) {
        if (locale !== 'en' && locale !== 'es') {
            console.error(`Invalid locale: ${locale}. Must be 'en' or 'es'`);
            return;
        }
        
        this.loadLocale(locale).then(() => {
            this.updateUI();
            this.updateLanguageButtons();
        });
    }
    
    /**
     * Translate a key
     * @param {string} key - Translation key
     * @returns {string} Translated text or key if not found
     */
    t(key) {
        return this.translations[key] || key;
    }
    
    /**
     * Update all UI elements with data-i18n attribute
     */
    updateUI() {
        document.querySelectorAll('[data-i18n]').forEach(el => {
            const key = el.getAttribute('data-i18n');
            const translation = this.t(key);
            
            // Update text content or placeholder
            if (el.tagName === 'INPUT' && el.type !== 'button') {
                el.placeholder = translation;
            } else {
                el.textContent = translation;
            }
        });
    }
    
    /**
     * Update language selector button states
     */
    updateLanguageButtons() {
        document.querySelectorAll('.lang-btn').forEach(btn => {
            const isActive = btn.dataset.lang === this.locale;
            btn.classList.toggle('active', isActive);
            btn.setAttribute('aria-pressed', isActive);
        });
    }
}

// Initialize i18n on page load
const i18n = new I18n('en');  // Default to English

// Load saved language or default
document.addEventListener('DOMContentLoaded', () => {
    i18n.loadLocale(i18n.locale).then(() => {
        i18n.updateUI();
        i18n.updateLanguageButtons();
    });
});
```

---

## 🎨 HTML IMPLEMENTATION

### Language Selector Component

```html
<!-- Language selector in header -->
<div class="language-selector">
    <button onclick="i18n.setLocale('en')" 
            class="lang-btn" 
            data-lang="en"
            aria-label="Switch to English"
            aria-pressed="true">
        🇬🇧 EN
    </button>
    <button onclick="i18n.setLocale('es')" 
            class="lang-btn" 
            data-lang="es"
            aria-label="Cambiar a Español"
            aria-pressed="false">
        🇪🇸 ES
    </button>
</div>
```

### CSS Styles

```css
.language-selector {
    display: flex;
    gap: 0.5rem;
    align-items: center;
}

.lang-btn {
    padding: 0.5rem 1rem;
    border: 1px solid rgba(255, 255, 255, 0.2);
    border-radius: 0.5rem;
    background: transparent;
    color: white;
    cursor: pointer;
    transition: all 0.2s ease;
    font-size: 0.875rem;
}

.lang-btn:hover {
    background: rgba(255, 255, 255, 0.1);
}

.lang-btn.active {
    font-weight: bold;
    border-color: #3b82f6;
    border-bottom: 2px solid #3b82f6;
    background: rgba(59, 130, 246, 0.1);
}

.lang-btn:focus {
    outline: 2px solid #3b82f6;
    outline-offset: 2px;
}
```

---

## 🧪 TESTING SCENARIOS

### Test 1: First Visit (Default English)
```
1. Clear all cookies
2. Navigate to http://localhost:8080
3. ✅ EXPECTED: UI loads in English
4. ✅ EXPECTED: No cookie is set yet
5. ✅ EXPECTED: English button is highlighted
```

### Test 2: Change to Spanish
```
1. Click "🇪🇸 ES" button
2. ✅ EXPECTED: UI changes to Spanish immediately
3. ✅ EXPECTED: Cookie "locale=es" is created
4. ✅ EXPECTED: Spanish button is highlighted
5. ✅ EXPECTED: Cookie expires in 365 days
```

### Test 3: Reload Page (Cookie Persistence)
```
1. With Spanish selected, refresh page (F5)
2. ✅ EXPECTED: Page loads in Spanish
3. ✅ EXPECTED: Spanish button is highlighted
4. ✅ EXPECTED: Cookie still present
```

### Test 4: Close and Reopen Browser
```
1. With Spanish selected, close browser
2. Reopen browser
3. Navigate to http://localhost:8080
4. ✅ EXPECTED: Page loads in Spanish
5. ✅ EXPECTED: Cookie persisted across sessions
```

### Test 5: Cookie Expiration
```
1. Manually set cookie expiration to past date
2. Refresh page
3. ✅ EXPECTED: Page loads in English (default)
4. ✅ EXPECTED: New cookie created when language selected
```

### Test 6: Invalid Cookie Value
```
1. Manually set cookie to invalid value (e.g., "locale=fr")
2. Refresh page
3. ✅ EXPECTED: Page loads in English (fallback)
4. ✅ EXPECTED: Error logged to console
```

### Test 7: Switch Between Languages
```
1. Start in English
2. Switch to Spanish → ✅ Immediate change
3. Switch to English → ✅ Immediate change
4. ✅ EXPECTED: Each change updates cookie
5. ✅ EXPECTED: No page reload required
```

---

## 🔒 SECURITY CONSIDERATIONS

### Cookie Attributes Explained

**SameSite=Strict**
- Prevents cookie from being sent in cross-site requests
- Protects against CSRF attacks
- Recommended for authentication-like cookies

**HttpOnly=false**
- Cookie accessible to JavaScript (required for i18n)
- **NOT for sensitive data** (only language preference)
- Safe for this use case

**Secure=false (development)**
- Allows cookie over HTTP in development
- **MUST be true in production** (HTTPS only)

**Path=/**
- Cookie available to entire app
- All pages can read language preference

### Privacy Compliance

**GDPR/Privacy**:
- Language preference is NOT personal data
- No consent required for functional cookies
- User can clear cookies anytime
- No tracking or analytics involved

**Cookie Notice**:
```html
<!-- Optional: Simple notice -->
<div class="cookie-notice">
    This app uses a cookie to remember your language preference.
    <a href="/privacy">Learn more</a>
</div>
```

---

## 📊 COOKIE LIFECYCLE

```
┌─────────────────────────────────────────────────────┐
│ User Visit Flow                                     │
├─────────────────────────────────────────────────────┤
│                                                     │
│  1. Page Load                                       │
│     ├─ Check for "locale" cookie                   │
│     ├─ Cookie found? Load saved language           │
│     └─ No cookie? Load English (default)           │
│                                                     │
│  2. User Clicks Language Selector                  │
│     ├─ Change UI language immediately              │
│     ├─ Save choice to cookie (365 days)            │
│     └─ Update button states                        │
│                                                     │
│  3. Subsequent Visits                              │
│     ├─ Cookie present → Load saved language        │
│     └─ Cookie expired → Load English               │
│                                                     │
│  4. Cookie Expiration (365 days later)             │
│     └─ Cookie deleted by browser                   │
│        └─ Next visit loads English (default)       │
│                                                     │
└─────────────────────────────────────────────────────┘
```

---

## 🚀 PRODUCTION CHECKLIST

- [ ] Cookie SameSite=Strict implemented
- [ ] Cookie expiration set to 365 days
- [ ] Default language is English
- [ ] Cookie read on every page load
- [ ] Cookie written on language change
- [ ] Visual feedback (active button)
- [ ] Console logs for debugging
- [ ] Error handling for invalid locales
- [ ] Fallback to English on error
- [ ] Accessibility (aria-pressed, aria-label)
- [ ] Mobile responsive
- [ ] Cross-browser tested (Chrome, Firefox, Safari, Edge)
- [ ] Cookie persistence across sessions verified
- [ ] Documentation updated

---

## 📚 REFERENCES

- [MDN: Document.cookie](https://developer.mozilla.org/en-US/docs/Web/API/Document/cookie)
- [MDN: SameSite cookies](https://developer.mozilla.org/en-US/docs/Web/HTTP/Headers/Set-Cookie/SameSite)
- [GDPR: Cookie guidelines](https://gdpr.eu/cookies/)
- [HTTP State Management](https://tools.ietf.org/html/rfc6265)

---

**Status**: Specified and ready for implementation  
**Priority**: HIGH (part of Phase 3)  
**Estimated time**: Included in 2-3 hours for Phase 3

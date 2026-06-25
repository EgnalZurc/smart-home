/**
 * i18n - Internationalization Engine
 * 
 * Features:
 * - Cookie-based locale persistence (365 days)
 * - Real-time language switching (no reload)
 * - Fallback to English if translation missing
 * - Automatic detection on first visit
 */

class I18n {
    constructor() {
        this.currentLocale = 'en';  // Default to English
        this.translations = {};
        this.fallbackLocale = 'en';
    }

    /**
     * Initialize i18n system
     */
    async init() {
        // Load locale from cookie or default to English
        this.currentLocale = this.getLocaleFromCookie() || 'en';
        
        // Load translations for current locale
        await this.loadTranslations(this.currentLocale);
        
        // If not English, also load English as fallback
        if (this.currentLocale !== 'en') {
            await this.loadTranslations('en');
        }
        
        // Apply translations to page
        this.applyTranslations();
        
        // Update language selector UI
        this.updateLanguageSelector();
    }

    /**
     * Load translation file for a locale
     */
    async loadTranslations(locale) {
        try {
            const response = await fetch(`/static/locales/${locale}.json`);
            const data = await response.json();
            this.translations[locale] = data;
        } catch (error) {
            console.error(`Failed to load translations for ${locale}:`, error);
        }
    }

    /**
     * Get translation for a key
     * @param {string} key - Translation key (e.g., 'header.title')
     * @param {string} locale - Optional locale override
     * @returns {string} Translated text
     */
    t(key, locale = null) {
        const targetLocale = locale || this.currentLocale;
        const keys = key.split('.');
        
        // Try to get translation from target locale
        let value = this.translations[targetLocale];
        for (const k of keys) {
            if (value && typeof value === 'object') {
                value = value[k];
            } else {
                value = undefined;
                break;
            }
        }
        
        // If found, return it
        if (value !== undefined) {
            return value;
        }
        
        // Fallback to English
        if (targetLocale !== this.fallbackLocale) {
            value = this.translations[this.fallbackLocale];
            for (const k of keys) {
                if (value && typeof value === 'object') {
                    value = value[k];
                } else {
                    value = undefined;
                    break;
                }
            }
            if (value !== undefined) {
                return value;
            }
        }
        
        // If still not found, return key itself
        return key;
    }

    /**
     * Apply translations to all elements with data-i18n attribute
     */
    applyTranslations() {
        document.querySelectorAll('[data-i18n]').forEach(element => {
            const key = element.getAttribute('data-i18n');
            element.textContent = this.t(key);
        });
        
        // Update placeholders
        document.querySelectorAll('[data-i18n-placeholder]').forEach(element => {
            const key = element.getAttribute('data-i18n-placeholder');
            element.placeholder = this.t(key);
        });
        
        // Update aria-labels
        document.querySelectorAll('[data-i18n-aria]').forEach(element => {
            const key = element.getAttribute('data-i18n-aria');
            element.setAttribute('aria-label', this.t(key));
        });
    }

    /**
     * Switch to a different locale
     * @param {string} locale - Target locale ('en' or 'es')
     */
    async switchLocale(locale) {
        if (locale === this.currentLocale) return;
        
        // Load translations if not already loaded
        if (!this.translations[locale]) {
            await this.loadTranslations(locale);
        }
        
        // Update current locale
        this.currentLocale = locale;
        
        // Save to cookie
        this.setLocaleCookie(locale);
        
        // Apply translations
        this.applyTranslations();
        
        // Update language selector
        this.updateLanguageSelector();
        
        // Dispatch custom event for other components to react
        window.dispatchEvent(new CustomEvent('localeChanged', { detail: { locale } }));
    }

    /**
     * Get locale from cookie
     * @returns {string|null} Locale code or null if not set
     */
    getLocaleFromCookie() {
        const cookies = document.cookie.split(';');
        for (const cookie of cookies) {
            const [name, value] = cookie.trim().split('=');
            if (name === 'locale') {
                return value;
            }
        }
        return null;
    }

    /**
     * Save locale to cookie (365 days expiration)
     * @param {string} locale - Locale code
     */
    setLocaleCookie(locale) {
        const expirationDate = new Date();
        expirationDate.setFullYear(expirationDate.getFullYear() + 1); // 365 days
        document.cookie = `locale=${locale}; expires=${expirationDate.toUTCString()}; path=/; SameSite=Lax`;
    }

    /**
     * Update language selector dropdown state
     */
    updateLanguageSelector() {
        const currentFlag = document.getElementById('current-flag');
        
        if (!currentFlag) return;
        
        // Update displayed flag image
        const flagPaths = {
            'en': '/static/flags/gb.svg',
            'es': '/static/flags/es.svg'
        };
        currentFlag.src = flagPaths[this.currentLocale];
        
        // Update active state in dropdown menu
        document.querySelectorAll('.lang-option').forEach(opt => {
            if (opt.dataset.lang === this.currentLocale) {
                opt.classList.add('active');
            } else {
                opt.classList.remove('active');
            }
        });
    }
}

// Create global i18n instance

// Create global i18n instance
const i18n = new I18n();

// Expose a promise that resolves when i18n is fully loaded
// app.js awaits window.i18nReady before starting the poll loop
window.i18n = i18n;
window.i18nReady = (document.readyState === 'loading')
    ? new Promise(resolve => document.addEventListener('DOMContentLoaded', () => i18n.init().then(resolve)))
    : i18n.init();

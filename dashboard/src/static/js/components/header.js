import { getCurrentErrors } from './errors.js';

export function updateConnectionStatus(mqttConnected, i18n) {
    // Support both old IDs and new component IDs
    const dot  = document.getElementById('cuchi-status-dot') || document.getElementById('status-dot');
    const line = document.getElementById('cuchi-status-text') || document.getElementById('status-line');
    if (!dot || !line) return;

    // If there are active errors, errors.js owns the status indicator — don't overwrite
    if (getCurrentErrors().length > 0) return;

    line.textContent = i18n.t(mqttConnected ? 'header.connected' : 'header.disconnected');
    line.style.color = '';
    // Use component classes if using new component, otherwise use Tailwind classes
    if (dot.classList.contains('cuchi-status-dot')) {
        dot.className = mqttConnected ? 'cuchi-status-dot online' : 'cuchi-status-dot offline';
    } else {
        dot.className = mqttConnected
            ? 'status-dot w-1.5 h-1.5 rounded-full bg-green-500'
            : 'w-1.5 h-1.5 rounded-full bg-red-400';
    }
    dot.textContent = '';
    dot.style.fontSize = '';
}

export function toggleLanguageMenu() {
    const menu = document.getElementById('cuchi-lang-menu') || document.getElementById('lang-menu');
    menu?.classList.toggle('open');
}

export function selectLanguage(locale, i18n) {
    const menu = document.getElementById('cuchi-lang-menu') || document.getElementById('lang-menu');
    menu?.classList.remove('open');
    const flags = { en: '/static/flags/gb.svg', es: '/static/flags/es.svg' };
    const currentFlag = document.getElementById('cuchi-current-flag') || document.getElementById('current-flag');
    if (currentFlag) currentFlag.src = flags[locale];
    document.querySelectorAll('.lang-option, .cuchi-lang-option').forEach(opt => {
        opt.classList.toggle('active', opt.dataset.lang === locale);
    });
    i18n.switchLocale(locale);
}

export function initLanguageDropdown(i18n) {
    document.addEventListener('click', e => {
        const dd = document.querySelector('.cuchi-lang-dropdown') || document.querySelector('.lang-dropdown');
        const menu = document.getElementById('cuchi-lang-menu') || document.getElementById('lang-menu');
        if (dd && !dd.contains(e.target)) {
            menu?.classList.remove('open');
        }
    });
}

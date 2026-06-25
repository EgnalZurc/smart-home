export function updateConnectionStatus(mqttConnected, i18n) {
    const dot  = document.getElementById('status-dot');
    const line = document.getElementById('status-line');
    line.textContent = i18n.t(mqttConnected ? 'header.connected' : 'header.disconnected');
    dot.className = mqttConnected
        ? 'status-dot w-1.5 h-1.5 rounded-full bg-green-500'
        : 'w-1.5 h-1.5 rounded-full bg-red-400';
}

export function toggleLanguageMenu() {
    document.getElementById('lang-menu').classList.toggle('open');
}

export function selectLanguage(locale, i18n) {
    document.getElementById('lang-menu').classList.remove('open');
    const flags = { en: '/static/flags/gb.svg', es: '/static/flags/es.svg' };
    document.getElementById('current-flag').src = flags[locale];
    document.querySelectorAll('.lang-option').forEach(opt => {
        opt.classList.toggle('active', opt.dataset.lang === locale);
    });
    i18n.switchLocale(locale);
}

export function initLanguageDropdown(i18n) {
    // Close on outside click
    document.addEventListener('click', e => {
        const dd = document.querySelector('.lang-dropdown');
        if (dd && !dd.contains(e.target)) {
            document.getElementById('lang-menu').classList.remove('open');
        }
    });
}

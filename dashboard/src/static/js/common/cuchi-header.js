/**
 * Cuchi Header Component
 * 
 * Unified header for all Cuchi Casa services.
 * Usage:
 *   <div id="cuchi-header"
 *        data-title="Smart Home"
 *        data-subtitle="Monitor inmobiliario"          <!-- optional -->
 *        data-i18n-key="header.title"                  <!-- optional: i18n key for title -->
 *        data-show-i18n="true"                         <!-- optional: show language flags -->
 *        data-status-endpoint="/api/health/ac-service" <!-- optional: health endpoint -->
 *        data-status-labels='{"online":"Conectado","offline":"Desconectado"}' <!-- optional -->
 *   >
 *       <!-- Optional: custom actions slot - will be placed in header-right before i18n/status -->
 *       <template data-slot="actions">
 *           <button class="my-btn">Custom Action</button>
 *       </template>
 *   </div>
 *   <script type="module" src="/static/js/common/cuchi-header.js"></script>
 * 
 * The component will render:
 *   [Home icon] [Title (+ subtitle)] ... [custom actions?] [i18n flags?] [Status dot + text?]
 */

const HEADER_CSS = `
.cuchi-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 1.5rem;
}
.cuchi-header-left {
    display: flex;
    align-items: center;
    gap: 0.75rem;
}
.cuchi-header-right {
    display: flex;
    align-items: center;
    gap: 0.75rem;
}
.cuchi-home-btn {
    display: flex;
    align-items: center;
    justify-content: center;
    width: 2rem;
    height: 2rem;
    border-radius: 0.5rem;
    border: 1px solid rgba(51, 65, 85, 0.5);
    background: rgba(30, 41, 59, 0.4);
    transition: all 0.15s ease;
    flex-shrink: 0;
    text-decoration: none;
}
.cuchi-home-btn:hover {
    border-color: rgba(71, 85, 105, 1);
    background: rgba(51, 65, 85, 0.4);
}
.cuchi-home-btn img {
    width: 1.25rem;
    height: 1.25rem;
    object-fit: contain;
    border-radius: 0.25rem;
}
.cuchi-title {
    font-size: 1.125rem;
    font-weight: 600;
    letter-spacing: -0.025em;
    color: white;
    margin: 0;
}
.cuchi-subtitle {
    font-size: 0.625rem;
    color: rgb(100, 116, 139);
    margin: 0;
}
.cuchi-title-wrap {
    display: flex;
    flex-direction: column;
}
/* Status indicator */
.cuchi-status {
    display: flex;
    align-items: center;
    gap: 0.375rem;
    cursor: default;
}
.cuchi-status-dot {
    width: 0.375rem;
    height: 0.375rem;
    border-radius: 50%;
    animation: cuchiPulse 2s infinite;
}
.cuchi-status-dot.online { background: rgb(34, 197, 94); }
.cuchi-status-dot.offline { background: rgb(239, 68, 68); }
.cuchi-status-dot.loading { background: rgb(100, 116, 139); }
.cuchi-status-text {
    font-size: 0.6875rem;
    color: rgb(148, 163, 184);
}
@keyframes cuchiPulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.5; } }
/* Language dropdown */
.cuchi-lang-dropdown { position: relative; }
.cuchi-lang-current {
    padding: 4px;
    border-radius: 6px;
    cursor: pointer;
    border: 2px solid rgba(100, 116, 139, 0.3);
    background: rgba(30, 41, 59, 0.4);
    transition: all 0.2s ease;
    display: flex;
    align-items: center;
    justify-content: center;
}
.cuchi-lang-current:hover {
    border-color: rgba(59, 130, 246, 0.5);
    background: rgba(59, 130, 246, 0.1);
    transform: scale(1.05);
}
.cuchi-flag-img {
    width: 24px;
    height: 16px;
    object-fit: cover;
    border-radius: 2px;
    display: block;
    box-shadow: 0 1px 2px rgba(0, 0, 0, 0.2);
}
.cuchi-lang-menu {
    position: absolute;
    top: calc(100% + 8px);
    right: 0;
    background: rgba(30, 41, 59, 0.95);
    border: 1px solid rgba(100, 116, 139, 0.4);
    border-radius: 8px;
    padding: 4px;
    display: none;
    flex-direction: column;
    gap: 4px;
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
    backdrop-filter: blur(10px);
    z-index: 1000;
    min-width: 50px;
}
.cuchi-lang-menu.open { display: flex; }
.cuchi-lang-option {
    padding: 4px;
    border-radius: 4px;
    cursor: pointer;
    transition: all 0.2s ease;
    display: flex;
    align-items: center;
    justify-content: center;
    border: 2px solid transparent;
}
.cuchi-lang-option:hover {
    background: rgba(59, 130, 246, 0.2);
    border-color: rgba(59, 130, 246, 0.4);
}
.cuchi-lang-option.active {
    background: rgba(59, 130, 246, 0.15);
    border-color: rgba(59, 130, 246, 0.5);
}
/* Actions slot */
.cuchi-header-actions {
    display: flex;
    align-items: center;
    gap: 0.5rem;
}
.cuchi-header-actions:empty {
    display: none;
}
`;

class CuchiHeader {
    constructor(container) {
        this.container = container;
        this.config = this.parseConfig();
        this.statusInterval = null;
        this.i18n = null;
        this.init();
    }

    parseConfig() {
        const c = this.container;
        let statusLabels = { online: 'Conectado', offline: 'Desconectado', loading: '--' };
        try {
            if (c.dataset.statusLabels) {
                statusLabels = { ...statusLabels, ...JSON.parse(c.dataset.statusLabels) };
            }
        } catch (e) { /* ignore */ }
        
        return {
            title: c.dataset.title || 'Cuchi Casa',
            subtitle: c.dataset.subtitle || null,
            i18nKey: c.dataset.i18nKey || null,
            showI18n: c.dataset.showI18n === 'true',
            statusEndpoint: c.dataset.statusEndpoint || null,
            showStatus: c.dataset.showStatus === 'true', // show status indicator without auto-polling
            statusLabels,
            homeUrl: c.dataset.homeUrl || '/smart-home',
            actionsId: c.dataset.actionsId || 'cuchi-header-actions', // custom ID for actions container
            showHome: c.dataset.showHome !== 'false', // default true, set to "false" to hide home button
        };
    }

    init() {
        this.injectStyles();
        this.render();
        if (this.config.statusEndpoint) {
            this.startStatusPolling();
        }
        if (this.config.showI18n) {
            this.initI18n();
        }
    }

    injectStyles() {
        if (document.getElementById('cuchi-header-styles')) return;
        const style = document.createElement('style');
        style.id = 'cuchi-header-styles';
        style.textContent = HEADER_CSS;
        document.head.appendChild(style);
    }

    render() {
        const { config } = this;
        
        // Extract custom actions slot before overwriting innerHTML
        const actionsTemplate = this.container.querySelector('template[data-slot="actions"]');
        const actionsHtml = actionsTemplate ? actionsTemplate.innerHTML : '';
        
        // Build title HTML
        let titleHtml;
        if (config.subtitle) {
            titleHtml = `
                <div class="cuchi-title-wrap">
                    <h1 class="cuchi-title" ${config.i18nKey ? `data-i18n="${config.i18nKey}"` : ''}>${config.title}</h1>
                    <p class="cuchi-subtitle">${config.subtitle}</p>
                </div>
            `;
        } else {
            titleHtml = `<h1 class="cuchi-title" ${config.i18nKey ? `data-i18n="${config.i18nKey}"` : ''}>${config.title}</h1>`;
        }

        // Build i18n HTML
        let i18nHtml = '';
        if (config.showI18n) {
            i18nHtml = `
                <div class="cuchi-lang-dropdown">
                    <div class="cuchi-lang-current" id="cuchi-lang-current">
                        <img id="cuchi-current-flag" src="/static/flags/gb.svg" alt="Language" class="cuchi-flag-img">
                    </div>
                    <div class="cuchi-lang-menu" id="cuchi-lang-menu">
                        <div class="cuchi-lang-option" data-lang="en" title="English">
                            <img src="/static/flags/gb.svg" alt="English" class="cuchi-flag-img">
                        </div>
                        <div class="cuchi-lang-option" data-lang="es" title="Español">
                            <img src="/static/flags/es.svg" alt="Español" class="cuchi-flag-img">
                        </div>
                    </div>
                </div>
            `;
        }

        // Build status HTML (show if endpoint defined OR manual status enabled)
        let statusHtml = '';
        if (config.statusEndpoint || config.showStatus) {
            statusHtml = `
                <div class="cuchi-status" id="cuchi-status">
                    <span class="cuchi-status-dot loading" id="cuchi-status-dot"></span>
                    <span class="cuchi-status-text" id="cuchi-status-text">${config.statusLabels.loading}</span>
                </div>
            `;
        }

        // Build home button HTML
        let homeHtml = '';
        if (config.showHome) {
            homeHtml = `
                <a href="${config.homeUrl}" class="cuchi-home-btn" aria-label="Dashboard" title="Cuchi Casa">
                    <img src="/static/icono-cuchi-casa.png" alt="Home">
                </a>
            `;
        }

        this.container.innerHTML = `
            <header class="cuchi-header">
                <div class="cuchi-header-left">
                    ${homeHtml}
                    ${titleHtml}
                </div>
                <div class="cuchi-header-right">
                    <div class="cuchi-header-actions" id="${config.actionsId}">${actionsHtml}</div>
                    ${i18nHtml}
                    ${statusHtml}
                </div>
            </header>
        `;

        // Bind events
        if (config.showI18n) {
            this.bindI18nEvents();
        }
    }

    bindI18nEvents() {
        const current = this.container.querySelector('#cuchi-lang-current');
        const menu = this.container.querySelector('#cuchi-lang-menu');
        const options = this.container.querySelectorAll('.cuchi-lang-option');

        if (current) {
            current.addEventListener('click', () => menu?.classList.toggle('open'));
        }

        options.forEach(opt => {
            opt.addEventListener('click', () => {
                const lang = opt.dataset.lang;
                this.selectLanguage(lang);
                menu?.classList.remove('open');
            });
        });

        // Close on outside click
        document.addEventListener('click', (e) => {
            const dropdown = this.container.querySelector('.cuchi-lang-dropdown');
            if (dropdown && !dropdown.contains(e.target)) {
                menu?.classList.remove('open');
            }
        });
    }

    selectLanguage(locale) {
        const flags = { en: '/static/flags/gb.svg', es: '/static/flags/es.svg' };
        const flagImg = this.container.querySelector('#cuchi-current-flag');
        if (flagImg) flagImg.src = flags[locale] || flags.en;
        
        this.container.querySelectorAll('.cuchi-lang-option').forEach(opt => {
            opt.classList.toggle('active', opt.dataset.lang === locale);
        });

        // Notify external i18n system if available
        if (this.i18n && typeof this.i18n.switchLocale === 'function') {
            this.i18n.switchLocale(locale);
        }
        
        // Dispatch event for external listeners
        this.container.dispatchEvent(new CustomEvent('languagechange', { 
            detail: { locale },
            bubbles: true 
        }));
    }

    async initI18n() {
        // Try to load the global i18n if available
        try {
            const stored = localStorage.getItem('cuchi-locale');
            if (stored) {
                this.selectLanguage(stored);
            }
        } catch (e) { /* ignore */ }
    }

    setI18n(i18nInstance) {
        this.i18n = i18nInstance;
    }

    startStatusPolling() {
        this.checkStatus();
        this.statusInterval = setInterval(() => this.checkStatus(), 10000);
    }

    async checkStatus() {
        const dot = this.container.querySelector('#cuchi-status-dot');
        const text = this.container.querySelector('#cuchi-status-text');
        if (!dot || !text) return;

        try {
            const resp = await fetch(this.config.statusEndpoint, { 
                method: 'GET',
                cache: 'no-store' 
            });
            const online = resp.ok;
            dot.className = `cuchi-status-dot ${online ? 'online' : 'offline'}`;
            text.textContent = online ? this.config.statusLabels.online : this.config.statusLabels.offline;
        } catch (e) {
            dot.className = 'cuchi-status-dot offline';
            text.textContent = this.config.statusLabels.offline;
        }
    }

    updateStatus(online, label = null) {
        const dot = this.container.querySelector('#cuchi-status-dot');
        const text = this.container.querySelector('#cuchi-status-text');
        if (dot) dot.className = `cuchi-status-dot ${online ? 'online' : 'offline'}`;
        if (text) text.textContent = label || (online ? this.config.statusLabels.online : this.config.statusLabels.offline);
    }

    destroy() {
        if (this.statusInterval) {
            clearInterval(this.statusInterval);
        }
    }
}

// Auto-initialize if container exists
const container = document.getElementById('cuchi-header');
if (container) {
    window.cuchiHeader = new CuchiHeader(container);
}

// Export for module usage
export { CuchiHeader };
export default CuchiHeader;

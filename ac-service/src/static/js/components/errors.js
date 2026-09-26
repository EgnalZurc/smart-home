// F0.30 - Backend error/warning notification system
import { showToast } from './toast.js';

let _lastHasErrors = false;
let _currentErrors = [];

export function updateErrorIndicator(errorsData, i18n) {
    const { errors, has_errors } = errorsData;
    _currentErrors = errors || [];

    const dot       = document.getElementById('status-dot');
    const line      = document.getElementById('status-line');
    const indicator = document.getElementById('status-indicator');
    if (!dot || !line) return;

    if (has_errors) {
        const worstIsError = errors.some(e => e.severity === 'error');
        // Replace dot with warning icon
        dot.className = '';
        dot.textContent = worstIsError ? '\u26a0\ufe0f' : '\u26a0\ufe0f';
        dot.style.fontSize = '14px';
        dot.style.lineHeight = '1';
        // Status text shows count
        const label = errors.length === 1 ? errors[0].source : `${errors.length} issues`;
        line.textContent = label;
        line.style.color = worstIsError ? '#f87171' : '#fbbf24';
        if (indicator) indicator.style.cursor = 'pointer';

        // Toast only when new errors appear
        if (!_lastHasErrors) {
            const msg = errors[0]?.message || 'Backend issue detected';
            showToast(msg, 'error', 5000);
        }
    } else {
        // Restore normal dot
        dot.className = 'status-dot w-1.5 h-1.5 rounded-full bg-green-500';
        dot.textContent = '';
        dot.style.fontSize = '';
        dot.style.lineHeight = '';
        line.style.color = '';
        if (indicator) indicator.style.cursor = 'default';
        // status-line text is managed by header.js (Connected/Disconnected)
        // Don't touch it here when no errors
    }

    _lastHasErrors = has_errors;
}

export function getCurrentErrors() {
    return _currentErrors;
}

export function openErrorsModal(errors, i18n) {
    const modal = document.getElementById('errors-modal');
    const list  = document.getElementById('errors-list');
    if (!modal || !list) return;

    const items = errors || _currentErrors;
    if (!items.length) {
        list.innerHTML = '<p class="text-center text-slate-500 text-sm py-4">No active errors \u2705</p>';
    } else {
        list.innerHTML = items.map(e => {
            const isError = e.severity === 'error';
            const color   = isError
                ? 'text-red-400 border-red-500/30 bg-red-500/5'
                : 'text-yellow-400 border-yellow-500/30 bg-yellow-500/5';
            const icon    = isError ? '\U0001f534' : '\U0001f7e1';
            const date    = new Date(e.timestamp * 1000);
            const ts      = date.toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit' })
                          + ' ' + date.toLocaleDateString('es-ES', { day: '2-digit', month: '2-digit' });
            return `<div class="rounded-xl px-3 py-2.5 border ${color} mb-2">
                <div class="flex items-start gap-2">
                    <span class="text-xs mt-0.5">${icon}</span>
                    <div class="flex-1 min-w-0">
                        <p class="text-sm font-medium">${e.message}</p>
                        <p class="text-[10px] text-slate-500 mt-0.5">${e.source} \u00b7 ${ts}</p>
                    </div>
                </div>
            </div>`;
        }).join('');
    }

    modal.classList.remove('hidden');
    requestAnimationFrame(() => modal.classList.add('modal-visible'));
}

export function closeErrorsModal() {
    const modal = document.getElementById('errors-modal');
    if (!modal) return;
    modal.classList.remove('modal-visible');
    setTimeout(() => modal.classList.add('hidden'), 300);
}

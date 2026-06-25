// F0.30 - Backend error/warning notification system
import { showToast } from './toast.js';

let _lastHasErrors = false;

export function updateErrorIndicator(errorsData, i18n) {
    const { errors, has_errors } = errorsData;
    const badge = document.getElementById('error-badge');
    const icon  = document.getElementById('error-icon');
    if (!badge || !icon) return;

    if (has_errors) {
        badge.textContent = errors.length;
        badge.classList.remove('hidden');
        icon.classList.add('text-yellow-400');
        icon.classList.remove('text-slate-500');
        // Show toast only on new errors appearing
        if (!_lastHasErrors) {
            const msg = errors[0]?.message || 'Backend error detected';
            showToast(msg, 'error', 5000);
        }
    } else {
        badge.classList.add('hidden');
        icon.classList.remove('text-yellow-400');
        icon.classList.add('text-slate-500');
    }
    _lastHasErrors = has_errors;
}

export function openErrorsModal(errors, i18n) {
    const modal = document.getElementById('errors-modal');
    const list  = document.getElementById('errors-list');
    if (!modal || !list) return;

    if (!errors.length) {
        list.innerHTML = '<p class="text-center text-slate-500 text-sm py-4">No active errors</p>';
    } else {
        list.innerHTML = errors.map(e => {
            const isError = e.severity === 'error';
            const color  = isError ? 'text-red-400 border-red-500/30 bg-red-500/5'
                                   : 'text-yellow-400 border-yellow-500/30 bg-yellow-500/5';
            const icon   = isError ? '🔴' : '🟡';
            const date   = new Date(e.timestamp * 1000);
            const ts     = date.toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit' })
                         + ' ' + date.toLocaleDateString('es-ES', { day: '2-digit', month: '2-digit' });
            return `<div class="rounded-xl px-3 py-2.5 border ${color} mb-2">
                <div class="flex items-start gap-2">
                    <span class="text-xs mt-0.5">${icon}</span>
                    <div class="flex-1 min-w-0">
                        <p class="text-sm font-medium">${e.message}</p>
                        <p class="text-[10px] text-slate-500 mt-0.5">${e.source} · ${ts}</p>
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

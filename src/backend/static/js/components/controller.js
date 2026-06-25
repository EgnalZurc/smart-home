import { postConfig } from '../services/api.js';
import { showToast } from './toast.js';

export let currentTarget = 26.0;

const DECISION_LABELS = {
    cooling_max: 'COOLING MAX', modulating: 'MODULANDO', off: 'OFF',
    cooldown: 'COOLDOWN', manual: 'MANUAL', system_off: 'SYSTEM OFF', error: 'ERROR',
};
const DECISION_COLORS = {
    cooling_max: '#60a5fa', modulating: '#fbbf24', off: '#64748b',
    cooldown: '#a78bfa', manual: '#4ade80', system_off: '#ef4444', error: '#ef4444',
};
const DECISION_BG = {
    cooling_max: 'rgba(96,165,250,0.15)',  modulating: 'rgba(251,191,36,0.15)',
    off: 'rgba(100,116,139,0.15)',         cooldown: 'rgba(167,139,250,0.15)',
    manual: 'rgba(74,222,128,0.15)',       system_off: 'rgba(239,68,68,0.15)',
    error: 'rgba(239,68,68,0.25)',
};

export function updateController(status) {
    currentTarget = status.target_temperature;
    document.getElementById('target-display').textContent = currentTarget.toFixed(1) + '?C';
    const el = document.getElementById('controller-decision');
    const action = status.ac_state.action;
    el.textContent           = DECISION_LABELS[action] || action;
    el.style.color           = DECISION_COLORS[action] || '#94a3b8';
    el.style.backgroundColor = DECISION_BG[action]     || 'transparent';
}

// i18n passed from app.js via window.i18n
export async function changeTarget(delta) {
    const i18n = window.i18n;
    currentTarget = Math.max(19, Math.min(30, currentTarget + delta));
    document.getElementById('target-display').textContent = currentTarget.toFixed(1) + '?C';
    try {
        await postConfig(currentTarget);
        showToast(
            i18n.t('toast.targetSet').replace('{{value}}', currentTarget.toFixed(1)),
            'success'
        );
    } catch {
        showToast(i18n.t('toast.targetError'), 'error');
    }
}

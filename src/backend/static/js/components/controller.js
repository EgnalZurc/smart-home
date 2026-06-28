import { postConfig, postManualParam } from '../services/api.js';
import { showToast } from './toast.js';

export let currentTarget   = 26.0;
export let currentManualT  = 24.0;

const ACTIVE_STATES   = new Set(['cooling_max', 'modulating', 'manual']);
const INACTIVE_STATES = new Set(['off', 'cooldown', 'system_off']);

const DECISION_LABELS = {
    cooling_max: 'COOLING MAX', modulating: 'MODULATING', off: 'OFF',
    cooldown: 'COOLDOWN',       manual: 'MANUAL',          system_off: 'SYSTEM OFF', error: 'ERROR',
};
const DECISION_COLORS = {
    cooling_max: '#60a5fa', modulating: '#fbbf24', off: '#64748b',
    cooldown: '#a78bfa',    manual: '#4ade80',      system_off: '#ef4444', error: '#ef4444',
};
const DECISION_BG = {
    cooling_max: 'rgba(96,165,250,0.15)',  modulating: 'rgba(251,191,36,0.15)',
    off: 'rgba(100,116,139,0.15)',         cooldown: 'rgba(167,139,250,0.15)',
    manual: 'rgba(74,222,128,0.15)',       system_off: 'rgba(239,68,68,0.15)',
    error: 'rgba(239,68,68,0.25)',
};

export function updateController(status) {
    const isManual = status.ac_state?.control_mode === 'manual';

    // Always reflect server state - no local overrides
    currentTarget  = status.target_temperature;
    currentManualT = status.manual_params?.temperature ?? 24.0;
    const displayTemp = isManual ? currentManualT : currentTarget;
    document.getElementById('target-display').textContent = displayTemp.toFixed(1) + '°C';

    const labelEl = document.getElementById('target-label');
    if (labelEl) {
        const i18n = window.i18n || { t: k => k };
        labelEl.textContent = isManual
            ? (i18n.t('controller.objectiveManual') || 'AC Temp')
            : (i18n.t('controller.objective') || 'Target');
    }

    const el     = document.getElementById('controller-decision');
    const action = status.ac_state.action;
    const acOn   = status.ac_real?.power === true;
    const acOff  = status.ac_real?.power === false;
    const wantsOn  = ACTIVE_STATES.has(action);
    const wantsOff = INACTIVE_STATES.has(action);
    const mismatch = (wantsOn && acOff) || (wantsOff && acOn);

    if (mismatch) {
        el.textContent           = DECISION_LABELS[action] || action;
        el.style.color           = '#fbbf24';
        el.style.backgroundColor = 'rgba(251,191,36,0.15)';
    } else {
        el.textContent           = DECISION_LABELS[action] || action;
        el.style.color           = DECISION_COLORS[action] || '#94a3b8';
        el.style.backgroundColor = DECISION_BG[action]     || 'transparent';
    }

    const pendingEl = document.getElementById('pending-indicator');
    if (pendingEl) pendingEl.classList.toggle('active', mismatch);

    const powerEl = document.getElementById('ac-real-power');
    if (powerEl) powerEl.style.display = 'none';
}

// changeTarget: sends the request and shows toast.
// Does NOT update the DOM - the next poll will reflect the new value.
export async function changeTarget(delta) {
    const i18n = window.i18n || { t: k => k };
    const isManual = document.getElementById('btn-manual')?.classList.contains('bg-blue-600');

    if (isManual) {
        const newTemp = Math.max(19, Math.min(30, currentManualT + delta));
        try {
            await postManualParam('temperature', newTemp);
            showToast(
                i18n.t('toast.setpointSet').replace('{{value}}', newTemp.toFixed(1)),
                'success'
            );
        } catch {
            showToast(i18n.t('toast.setpointError'), 'error');
        }
    } else {
        const newTemp = Math.max(19, Math.min(30, currentTarget + delta));
        try {
            await postConfig(newTemp);
            showToast(
                i18n.t('toast.targetSet').replace('{{value}}', newTemp.toFixed(1)),
                'success'
            );
        } catch {
            showToast(i18n.t('toast.targetError'), 'error');
        }
    }
}

import { postConfig } from '../services/api.js';
import { showToast } from './toast.js';

export let currentTarget = 26.0;

// States where the AC should be ON according to the controller
const ACTIVE_STATES = new Set(['cooling_max', 'modulating', 'manual']);
// States where the AC should be OFF
const INACTIVE_STATES = new Set(['off', 'cooldown', 'system_off']);

const DECISION_LABELS = {
    cooling_max: 'COOLING MAX',
    modulating:  'MODULATING',
    off:         'OFF',
    cooldown:    'COOLDOWN',
    manual:      'MANUAL',
    system_off:  'SYSTEM OFF',
    error:       'ERROR',
};

// Base colors when AC real state matches controller expectation
const DECISION_COLORS = {
    cooling_max:  '#60a5fa',
    modulating:   '#fbbf24',
    off:          '#64748b',
    cooldown:     '#a78bfa',
    manual:       '#4ade80',
    system_off:   '#ef4444',
    error:        '#ef4444',
};
const DECISION_BG = {
    cooling_max:  'rgba(96,165,250,0.15)',
    modulating:   'rgba(251,191,36,0.15)',
    off:          'rgba(100,116,139,0.15)',
    cooldown:     'rgba(167,139,250,0.15)',
    manual:       'rgba(74,222,128,0.15)',
    system_off:   'rgba(239,68,68,0.15)',
    error:        'rgba(239,68,68,0.25)',
};

export function updateController(status) {
    currentTarget = status.target_temperature;
    document.getElementById('target-display').textContent = currentTarget.toFixed(1) + '\u00b0C';

    const el     = document.getElementById('controller-decision');
    const action = status.ac_state.action;
    const acOn   = status.ac_real?.power === true;
    const acOff  = status.ac_real?.power === false;

    // Detect discrepancy: controller wants AC on but it's still off (or vice versa)
    const wantsOn   = ACTIVE_STATES.has(action);
    const wantsOff  = INACTIVE_STATES.has(action);
    const mismatch  = (wantsOn && acOff) || (wantsOff && acOn);

    if (mismatch) {
        // Transitioning — amber color to signal pending confirmation
        el.textContent           = DECISION_LABELS[action] || action;
        el.style.color           = '#fbbf24';
        el.style.backgroundColor = 'rgba(251,191,36,0.15)';
    } else {
        el.textContent           = DECISION_LABELS[action] || action;
        el.style.color           = DECISION_COLORS[action] || '#94a3b8';
        el.style.backgroundColor = DECISION_BG[action]     || 'transparent';
    }

    // F0.37: Show/hide pending indicator
    const pendingEl = document.getElementById('pending-indicator');
    if (pendingEl) {
        if (mismatch) {
            pendingEl.classList.add('active');
        } else {
            pendingEl.classList.remove('active');
        }
    }

    // Remove ac-real-power as separate element — badge is now the single source of truth
    // (element may still exist in DOM for backward compat; hide it)
    const powerEl = document.getElementById('ac-real-power');
    if (powerEl) powerEl.style.display = 'none';
}

// i18n passed from app.js via window.i18n
export async function changeTarget(delta) {
    const i18n = window.i18n;
    currentTarget = Math.max(19, Math.min(30, currentTarget + delta));
    document.getElementById('target-display').textContent = currentTarget.toFixed(1) + '\u00b0C';
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

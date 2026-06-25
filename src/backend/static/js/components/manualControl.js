import { postControlMode } from '../services/api.js';
import { showToast } from './toast.js';

export let currentControlMode = 'off';

export function updateControlModeButtons() {
    const activeClasses = {
        auto:   'btn-control py-3 rounded-xl bg-green-600 text-sm font-semibold border border-green-500',
        manual: 'btn-control py-3 rounded-xl bg-blue-600  text-sm font-semibold border border-blue-500',
        off:    'btn-control py-3 rounded-xl bg-red-600   text-sm font-semibold border border-red-500',
    };
    const inactive = 'btn-control py-3 rounded-xl bg-slate-700/60 text-sm font-semibold border border-transparent';
    for (const [mode, id] of [['auto','btn-auto'],['manual','btn-manual'],['off','btn-off']]) {
        document.getElementById(id).className = currentControlMode === mode ? activeClasses[mode] : inactive;
    }
}

export function syncControlMode(mode) {
    currentControlMode = mode;
    updateControlModeButtons();
}

export async function setControlMode(mode) {
    const i18n = window.i18n;
    try {
        await postControlMode(mode);
        currentControlMode = mode;
        updateControlModeButtons();
        const modeLabel = i18n.t(`manualControl.${mode}`) || mode.toUpperCase();
        showToast(
            i18n.t('toast.controlModeSet').replace('{{value}}', modeLabel),
            'success'
        );
    } catch {
        showToast(i18n.t('toast.controlModeError'), 'error');
    }
}

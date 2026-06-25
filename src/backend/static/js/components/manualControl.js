import { postControlMode } from '../services/api.js';
import { showToast } from './toast.js';

export let currentControlMode = 'off';

export function updateControlModeButtons() {
    const modes = { auto: 'btn-auto', manual: 'btn-manual', off: 'btn-off' };
    const activeClasses = {
        auto:   'btn-control py-3 rounded-xl bg-green-600 text-sm font-semibold border border-green-500',
        manual: 'btn-control py-3 rounded-xl bg-blue-600  text-sm font-semibold border border-blue-500',
        off:    'btn-control py-3 rounded-xl bg-red-600   text-sm font-semibold border border-red-500',
    };
    const inactiveClass = 'btn-control py-3 rounded-xl bg-slate-700/60 text-sm font-semibold border border-transparent';

    for (const [mode, id] of Object.entries(modes)) {
        document.getElementById(id).className =
            currentControlMode === mode ? activeClasses[mode] : inactiveClass;
    }
}

export function syncControlMode(mode) {
    currentControlMode = mode;
    updateControlModeButtons();
}

export async function setControlMode(mode) {
    try {
        await postControlMode(mode);
        currentControlMode = mode;
        updateControlModeButtons();
        showToast(`Mode: ${mode.toUpperCase()}`, 'success');
    } catch {
        showToast('Error changing control mode', 'error');
    }
}

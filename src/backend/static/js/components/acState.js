import { ManualControlQueue } from '../services/manualQueue.js';
import { showToast } from './toast.js';
import { tempColor } from '../utils/colors.js';

export const manualQueue = new ManualControlQueue();

export function updateAcState(status, i18n) {
    const { ac_state, ac_real, manual_params } = status;
    const control_mode = ac_state.control_mode;

    // Sync last acknowledged values from polled state
    if (manual_params) {
        manualQueue.lastAcknowledged = {
            mode:        manual_params.mode,
            fan_speed:   manual_params.fan_speed,
            temperature: manual_params.temperature,
        };
    }

    updateModeDisplay(ac_state.mode, i18n);
    updateFanDisplay(ac_state.fan_speed, i18n);

    const rtEl = document.getElementById('ac-real-roomtemp');
    if (rtEl) {
        if (ac_real.room_temp !== null) {
            rtEl.textContent = ac_real.room_temp.toFixed(1) + '°C';
            rtEl.style.color = tempColor(ac_real.room_temp);
        } else {
            rtEl.textContent = '—';
            rtEl.style.color = '#64748b';
        }
    }

    const isManual = control_mode === 'manual';
    ['ac-mode-box', 'ac-fan-box'].forEach(id => {
        document.getElementById(id).style.cursor = isManual ? 'pointer' : 'default';
    });
}

export function editMode(i18n) {
    const current = manualQueue.lastAcknowledged.mode;
    const newMode = current === 'cool' ? 'heat' : 'cool';
    const modeLabel = newMode === 'cool'
        ? i18n.t('modals.forceOn.modes.cool')
        : i18n.t('modals.forceOn.modes.heat');

    manualQueue.enqueue(
        'mode', newMode,
        () => showToast(i18n.t('toast.modeSet').replace('{{value}}', modeLabel), 'success'),
        () => showToast(i18n.t('toast.modeError'), 'error')
    );
}

export function editFanSpeed(i18n) {
    const newSpeed = (manualQueue.lastAcknowledged.fan_speed + 1) % 4;
    const speedLabels = [
        i18n.t('modals.forceOn.powerLevels.auto'),
        i18n.t('modals.forceOn.powerLevels.low'),
        i18n.t('modals.forceOn.powerLevels.medium'),
        i18n.t('modals.forceOn.powerLevels.high'),
    ];

    manualQueue.enqueue(
        'fan_speed', newSpeed,
        () => showToast(i18n.t('toast.fanSet').replace('{{value}}', speedLabels[newSpeed]), 'success'),
        () => showToast(i18n.t('toast.fanError'), 'error')
    );
}

export function updateModeDisplay(mode, i18n) {
    document.getElementById('ac-mode-display').textContent = mode === 'cool'
        ? i18n.t('modals.forceOn.modes.cool')
        : i18n.t('modals.forceOn.modes.heat');
}

export function updateFanDisplay(speed, i18n) {
    const labels = [
        i18n.t('modals.forceOn.powerLevels.auto'),
        i18n.t('modals.forceOn.powerLevels.low'),
        i18n.t('modals.forceOn.powerLevels.medium'),
        i18n.t('modals.forceOn.powerLevels.high'),
    ];
    const colors = ['text-white', 'text-blue-400', 'text-green-400', 'text-red-400'];
    const el = document.getElementById('ac-fan-display');
    el.textContent = labels[speed];
    el.className = `text-xs font-semibold ${colors[speed]}`;
}

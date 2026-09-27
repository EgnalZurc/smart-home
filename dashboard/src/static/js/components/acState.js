import { ManualControlQueue } from '../services/manualQueue.js';
import { showToast } from './toast.js';
import { tempColor } from '../utils/colors.js';

export const manualQueue = new ManualControlQueue();

// -- Pending UI helpers --------------------------------------------------------
// Called by manualQueue when a command is sent but not yet confirmed by server.
// Shows a sweep animation + amber value on the relevant control.
function _setPendingUI(param, value) {
    if (param === 'mode') {
        const box = document.getElementById('ac-mode-box');
        const display = document.getElementById('ac-mode-display');
        if (box) box.classList.add('param-pending');
        if (display) display.classList.add('param-pending-value');
    } else if (param === 'fan_speed') {
        const box = document.getElementById('ac-fan-box');
        const display = document.getElementById('ac-fan-display');
        if (box) box.classList.add('param-pending');
        if (display) display.classList.add('param-pending-value');
    } else if (param === 'temperature') {
        const display = document.getElementById('target-display');
        const minusBtn = document.querySelector('[aria-label="Decrease temperature"]');
        const plusBtn  = document.querySelector('[aria-label="Increase temperature"]');
        if (display) display.classList.add('param-pending-value');
        if (minusBtn) minusBtn.classList.add('param-pending');
        if (plusBtn)  plusBtn.classList.add('param-pending');
    }
}

function _clearPendingUI(param) {
    if (param === 'mode') {
        document.getElementById('ac-mode-box')?.classList.remove('param-pending');
        document.getElementById('ac-mode-display')?.classList.remove('param-pending-value');
    } else if (param === 'fan_speed') {
        document.getElementById('ac-fan-box')?.classList.remove('param-pending');
        document.getElementById('ac-fan-display')?.classList.remove('param-pending-value');
    } else if (param === 'temperature') {
        document.getElementById('target-display')?.classList.remove('param-pending-value');
        document.querySelector('[aria-label="Decrease temperature"]')?.classList.remove('param-pending');
        document.querySelector('[aria-label="Increase temperature"]')?.classList.remove('param-pending');
    }
}

// Register UI callbacks with the queue
manualQueue.registerUI(_setPendingUI, _clearPendingUI);

// -- Update from poll ----------------------------------------------------------
export function updateAcState(status, i18n) {
    const { ac_state, ac_real, manual_params } = status;
    const control_mode = ac_state.control_mode;

    if (manual_params) {
        manualQueue.lastAcknowledged = {
            mode:        manual_params.mode,
            fan_speed:   manual_params.fan_speed,
            temperature: manual_params.temperature,
        };
        // Notify queue of polled values so it can clear pending state
        manualQueue.onPollUpdate('mode',      manual_params.mode);
        manualQueue.onPollUpdate('fan_speed', manual_params.fan_speed);
        manualQueue.onPollUpdate('temperature', manual_params.temperature);
    }

    updateModeDisplay(ac_state.mode, i18n);
    updateFanDisplay(ac_state.fan_speed, i18n);

    const rtEl = document.getElementById('ac-real-roomtemp');
    if (rtEl) {
        if (ac_real.room_temp !== null) {
            rtEl.textContent = ac_real.room_temp.toFixed(1) + '\u00b0C';
            rtEl.style.color = tempColor(ac_real.room_temp);
        } else {
            rtEl.textContent = '\u2014';
            rtEl.style.color = '#64748b';
        }
    }

    const isManual = control_mode === 'manual';
    ['ac-mode-box', 'ac-fan-box'].forEach(id => {
        const el = document.getElementById(id);
        if (el && !el.classList.contains('param-pending')) {
            el.style.cursor = isManual ? 'pointer' : 'default';
        }
    });
}

// -- Actions ------------------------------------------------------------------
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

// -- Display helpers (always from server state) --------------------------------
export function updateModeDisplay(mode, i18n) {
    const el = document.getElementById('ac-mode-display');
    if (!el || el.classList.contains('param-pending-value')) return; // don't overwrite pending
    el.textContent = mode === 'cool'
        ? i18n.t('modals.forceOn.modes.cool')
        : i18n.t('modals.forceOn.modes.heat');
}

export function updateFanDisplay(speed, i18n) {
    const el = document.getElementById('ac-fan-display');
    if (!el || el.classList.contains('param-pending-value')) return; // don't overwrite pending
    const labels = [
        i18n.t('modals.forceOn.powerLevels.auto'),
        i18n.t('modals.forceOn.powerLevels.low'),
        i18n.t('modals.forceOn.powerLevels.medium'),
        i18n.t('modals.forceOn.powerLevels.high'),
    ];
    const colors = ['text-white', 'text-blue-400', 'text-green-400', 'text-red-400'];
    el.textContent = labels[speed];
    el.className = `text-xs font-semibold ${colors[speed]}`;
}

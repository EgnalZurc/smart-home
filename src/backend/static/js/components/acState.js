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
    updateSetpointDisplay(ac_state.setpoint);

    // Thermostat (read-only, from MELCloud)
    const rtEl = document.getElementById('ac-real-roomtemp');
    if (ac_real.room_temp !== null) {
        rtEl.textContent = ac_real.room_temp.toFixed(1) + '°C';
        rtEl.style.color = tempColor(ac_real.room_temp);
    } else {
        rtEl.textContent = '—';
        rtEl.style.color = '#64748b';
    }

    // Power indicator
    const powerEl = document.getElementById('ac-real-power');
    if (ac_real.power === null) {
        powerEl.textContent = '--'; powerEl.style.color = '#64748b';
    } else if (!ac_real.power) {
        powerEl.textContent = 'OFF'; powerEl.style.color = '#ef4444';
    } else {
        powerEl.textContent = 'ON'; powerEl.style.color = '#4ade80';
    }

    // Enable/disable param boxes based on control mode
    const isManual = control_mode === 'manual';
    ['ac-mode-box', 'ac-fan-box', 'ac-setpoint-box'].forEach(id => {
        document.getElementById(id).style.cursor = isManual — 'pointer' : 'default';
    });
}

export function editMode(i18n) {
    const current = manualQueue.lastAcknowledged.mode;
    const newMode = current === 'cool' — 'heat' : 'cool';
    const box = document.getElementById('ac-mode-box');
    const modeLabel = newMode === 'cool'
        — i18n.t('modals.forceOn.modes.cool')
        : i18n.t('modals.forceOn.modes.heat');

    manualQueue.enqueue(
        'mode', newMode,
        val => updateModeDisplay(val, i18n),
        val => {
            updateModeDisplay(val, i18n);
            _shake(box);
            showToast(i18n.t('toast.modeError'), 'error');
        },
        () => showToast(i18n.t('toast.modeSet').replace('{{value}}', modeLabel), 'success')
    );
    _pulse(box);
}

export function editFanSpeed(i18n) {
    const newSpeed = (manualQueue.lastAcknowledged.fan_speed + 1) % 4;
    const speedLabels = [
        i18n.t('modals.forceOn.powerLevels.auto'),
        i18n.t('modals.forceOn.powerLevels.low'),
        i18n.t('modals.forceOn.powerLevels.medium'),
        i18n.t('modals.forceOn.powerLevels.high'),
    ];
    const box = document.getElementById('ac-fan-box');

    manualQueue.enqueue(
        'fan_speed', newSpeed,
        val => updateFanDisplay(val, i18n),
        val => {
            updateFanDisplay(val, i18n);
            _shake(box);
            showToast(i18n.t('toast.fanError'), 'error');
        },
        () => showToast(i18n.t('toast.fanSet').replace('{{value}}', speedLabels[newSpeed]), 'success')
    );
    _pulse(box);
}

export function editSetpoint(i18n) {
    const current = manualQueue.lastAcknowledged.temperature;
    const input = prompt(`${i18n.t('modals.forceOn.temperature')} (19-30°C):`, current);
    if (input === null) return;
    const temp = parseFloat(input);
    if (isNaN(temp) || temp < 19 || temp > 30) {
        showToast(i18n.t('toast.invalidTemp'), 'warning');
        return;
    }
    const box = document.getElementById('ac-setpoint-box');

    manualQueue.enqueue(
        'temperature', temp,
        val => updateSetpointDisplay(val),
        val => {
            updateSetpointDisplay(val);
            _shake(box);
            showToast(i18n.t('toast.setpointError'), 'error');
        },
        () => showToast(i18n.t('toast.setpointSet').replace('{{value}}', temp.toFixed(1)), 'success')
    );
    _pulse(box);
}

export function updateModeDisplay(mode, i18n) {
    document.getElementById('ac-mode-display').textContent = mode === 'cool'
        — i18n.t('modals.forceOn.modes.cool')
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

export function updateSetpointDisplay(temp) {
    document.getElementById('ac-setpoint-display').textContent = temp.toFixed(1) + '°C';
}

function _pulse(el) {
    el.classList.add('optimistic-update');
    setTimeout(() => el.classList.remove('optimistic-update'), 600);
}

function _shake(el) {
    el.classList.add('revert-error');
    setTimeout(() => el.classList.remove('revert-error'), 500);
}

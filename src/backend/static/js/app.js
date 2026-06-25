// app.js - Main orchestrator. Wires all modules together.
import { fetchStatus, fetchSensors, fetchOutdoor, fetchErrors } from './services/api.js';
import { loadHistory, updateHistory }              from './services/sensorHistory.js';
import { updateAvgTemp, updateOutdoor, updateSensorsCount, updateSensorsDetail, openModal, closeModal } from './components/avgTemp.js';
import { updateAcState, editMode, editFanSpeed, editSetpoint } from './components/acState.js';
import { updateController, changeTarget }          from './components/controller.js';
import { syncControlMode, setControlMode }         from './components/manualControl.js';
import { initCharts, updateTempChart, updateHumChart } from './components/charts.js';
import { updateConnectionStatus, toggleLanguageMenu, selectLanguage, initLanguageDropdown } from './components/header.js';
import { showToast }                               from './components/toast.js';
import { updateErrorIndicator, openErrorsModal, closeErrorsModal } from './components/errors.js';

const i18n = window.i18n;

let _wasConnected = true; // track connection state for toast on reconnect/disconnect

// —— Poll ————————————————————————————————————————————————————————————————————
async function poll() {
    try {
        const [status, sensData] = await Promise.all([fetchStatus(), fetchSensors()]);
        const sensors = sensData.sensors || [];

        // Toast on connection state change
        if (!_wasConnected) {
            // Reconnected — no toast needed, status dot is enough
            _wasConnected = true;
        }

        updateAvgTemp(status);
        updateConnectionStatus(status.mqtt_connected, i18n);
        updateAcState(status, i18n);
        updateController(status);
        syncControlMode(status.ac_state.control_mode || 'auto');

        try {
            const out = await fetchOutdoor();
            updateOutdoor(out, i18n);
        } catch { /* outdoor is optional, no toast */ }

        // F0.30 - Check backend errors
        try {
            const errData = await fetchErrors();
            updateErrorIndicator(errData, i18n);
        } catch { /* errors endpoint is optional */ }

        await updateHistory();
        updateSensorsCount(sensors);
        updateTempChart(sensors, i18n);
        updateHumChart(sensors, i18n);
        updateSensorsDetail(sensors, i18n);

    } catch (err) {
        console.error('Poll error:', err);
        document.getElementById('status-line').textContent = 'Error';
        document.getElementById('status-dot').className = 'w-1.5 h-1.5 rounded-full bg-red-400';
        // Only show toast once when connection is lost, not on every failed poll
        if (_wasConnected) {
            showToast(i18n.t('toast.connectionLost'), 'error', 5000);
            _wasConnected = false;
        }
    }
}

// —— Init ————————————————————————————————————————————————————————————————————
(async function init() {
    // Wait for i18n translations to load before rendering
    await window.i18nReady;
    initCharts();
    initLanguageDropdown(i18n);
    await loadHistory();
    await poll();
    setInterval(poll, 5000);
})();

// —— Global handlers (called from HTML onclick) ———————————————————————————————
window.openModal      = openModal;
window.closeModal     = closeModal;
window.changeTarget   = changeTarget;
window.setControlMode = mode => setControlMode(mode);
window.editMode       = () => editMode(i18n);
window.editFanSpeed   = () => editFanSpeed(i18n);
window.editSetpoint   = () => editSetpoint(i18n);
window.openErrorsModal  = () => { fetchErrors().then(d => openErrorsModal(d.errors || [], i18n)).catch(() => openErrorsModal([], i18n)); };
window.closeErrorsModal = closeErrorsModal;
// Clicking the status indicator opens errors modal only when there are errors
window.onStatusClick    = () => { fetchErrors().then(d => { if (d.has_errors) openErrorsModal(d.errors || [], i18n); }).catch(() => {}); };
window.toggleLanguageMenu = toggleLanguageMenu;
window.selectLanguage     = locale => selectLanguage(locale, i18n);

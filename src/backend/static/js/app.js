// app.js - Main orchestrator. Wires all modules together.
import { fetchStatus, fetchSensors, fetchOutdoor } from './services/api.js';
import { loadHistory, updateHistory }              from './services/sensorHistory.js';
import { updateAvgTemp, updateOutdoor, updateSensorsCount, updateSensorsDetail, openModal, closeModal } from './components/avgTemp.js';
import { updateAcState, editMode, editFanSpeed, editSetpoint, manualQueue } from './components/acState.js';
import { updateController, changeTarget }          from './components/controller.js';
import { syncControlMode, setControlMode }         from './components/manualControl.js';
import { initCharts, updateTempChart, updateHumChart } from './components/charts.js';
import { updateConnectionStatus, toggleLanguageMenu, selectLanguage, initLanguageDropdown } from './components/header.js';
import { showToast }                               from './components/toast.js';

// i18n is loaded as a global by i18n.js (legacy script tag)
const i18n = window.i18n;

// ?? Poll ????????????????????????????????????????????????????????????????????
async function poll() {
    try {
        const [status, sensData] = await Promise.all([fetchStatus(), fetchSensors()]);
        const sensors = sensData.sensors || [];

        updateAvgTemp(status);
        updateConnectionStatus(status.mqtt_connected, i18n);
        updateAcState(status, i18n);
        updateController(status);
        syncControlMode(status.ac_state.control_mode || 'auto');

        try {
            const out = await fetchOutdoor();
            updateOutdoor(out, i18n);
        } catch { /* outdoor optional */ }

        await updateHistory();
        updateSensorsCount(sensors);
        updateTempChart(sensors, i18n);
        updateHumChart(sensors, i18n);
        updateSensorsDetail(sensors, i18n);

    } catch (err) {
        console.error('Poll error:', err);
        document.getElementById('status-line').textContent = 'Error';
        document.getElementById('status-dot').className = 'w-1.5 h-1.5 rounded-full bg-red-400';
    }
}

// ?? Init ????????????????????????????????????????????????????????????????????
(async function init() {
    initCharts();
    initLanguageDropdown(i18n);
    await loadHistory();
    await poll();
    setInterval(poll, 5000);
})();

// ?? Global handlers (called from HTML onclick) ???????????????????????????????
// These are exposed on window so the HTML onclick attributes still work.
window.openModal     = openModal;
window.closeModal    = closeModal;
window.changeTarget  = changeTarget;
window.setControlMode = mode => setControlMode(mode);
window.editMode      = () => editMode(i18n);
window.editFanSpeed  = () => editFanSpeed(i18n);
window.editSetpoint  = () => editSetpoint(i18n);
window.toggleLanguageMenu = toggleLanguageMenu;
window.selectLanguage     = locale => selectLanguage(locale, i18n);

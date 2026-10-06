// app.js - Main orchestrator. Wires all modules together.
import { fetchStatus, fetchSensors, fetchOutdoor, fetchErrors } from './services/api.js';
import { loadHistory, updateHistory }              from './services/sensorHistory.js';
import { updateAvgTemp, updateOutdoor, updateSensorsCount, updateSensorsDetail, openModal, closeModal } from './components/avgTemp.js';
import { updateAcState, editMode, editFanSpeed } from './components/acState.js';
import { updateController, changeTarget }          from './components/controller.js';
import { syncControlMode, setControlMode }         from './components/manualControl.js';
import { initCharts, setSensors, refreshChart, retranslateCharts, initChartTabs } from './components/charts.js';
import { updateConnectionStatus, toggleLanguageMenu, selectLanguage, initLanguageDropdown } from './components/header.js';
import { showToast }                               from './components/toast.js';
import { updateErrorIndicator, openErrorsModal, closeErrorsModal } from './components/errors.js';

const i18n = window.i18n;

let _wasConnected = true;

// -- Poll -----------------------------------------------------------------------
async function poll() {
    try {
        const [status, sensData] = await Promise.all([fetchStatus(), fetchSensors()]);
        const sensors = sensData.sensors || [];

        if (!_wasConnected) { _wasConnected = true; }

        updateAvgTemp(status);
        updateConnectionStatus(status.mqtt_connected, i18n);
        updateAcState(status, i18n);
        updateController(status);
        syncControlMode(status.ac_state.control_mode || 'auto');

        try {
            const out = await fetchOutdoor();
            updateOutdoor(out, i18n);
        } catch { /* outdoor is optional */ }

        try {
            const errData = await fetchErrors();
            updateErrorIndicator(errData, i18n);
        } catch { /* errors endpoint is optional */ }

        await updateHistory();
        updateSensorsCount(sensors);
        updateSensorsDetail(sensors, i18n, status.ac_real);

        // Dynamic chart: update sensor list (with A/C room temp) and refresh
        const acRoomTemp = status?.ac_real?.room_temp ?? null;
        setSensors(sensors, acRoomTemp);
        await refreshChart();

    } catch (err) {
        console.error('Poll error:', err);
        document.getElementById('status-line').textContent = 'Error';
        document.getElementById('status-dot').className = 'w-1.5 h-1.5 rounded-full bg-red-400';
        if (_wasConnected) {
            showToast(i18n.t('toast.connectionLost'), 'error', 5000);
            _wasConnected = false;
        }
    }
}

// -- Overlay helpers (F0.33) ---------------------------------------------------
function showApp() {
    const overlay = document.getElementById('loading-overlay');
    const content = document.getElementById('app-content');
    if (content) content.classList.add('visible');
    if (overlay) {
        overlay.classList.add('fade-out');
        setTimeout(() => { overlay.style.display = 'none'; }, 450);
    }
}

// -- Init ----------------------------------------------------------------------
(async function init() {
    const i18nPromise = (window.i18n && typeof window.i18n.init === 'function')
        ? window.i18n.init().catch(() => {})
        : Promise.resolve();
    await Promise.race([i18nPromise, new Promise(r => setTimeout(r, 4000))]);

    const resolvedI18n = window.i18n || { t: k => k };
    initCharts(resolvedI18n);
    initChartTabs();
    initLanguageDropdown(resolvedI18n);

    try {
        await Promise.race([loadHistory(), new Promise(r => setTimeout(r, 4000))]);
    } catch { /* non-fatal */ }

    try {
        await Promise.race([poll(), new Promise(r => setTimeout(r, 6000))]);
    } catch { /* non-fatal */ }

    showApp();
    setInterval(poll, 5000);
})();

// -- Global handlers (called from HTML onclick) --------------------------------

window.openModal      = openModal;
window.closeModal     = closeModal;
window.changeTarget   = changeTarget;
window.setControlMode = mode => setControlMode(mode);
window.editMode       = () => editMode(i18n);
window.editFanSpeed   = () => editFanSpeed(i18n);
window.openErrorsModal  = () => { fetchErrors().then(d => openErrorsModal(d.errors || [], i18n)).catch(() => openErrorsModal([], i18n)); };
window.closeErrorsModal = closeErrorsModal;
window.onStatusClick    = () => { fetchErrors().then(d => { if (d.has_errors) openErrorsModal(d.errors || [], i18n); }).catch(() => {}); };
window.toggleLanguageMenu = toggleLanguageMenu;
window.selectLanguage     = locale => {
    selectLanguage(locale, i18n);
    retranslateCharts(window.i18n || i18n);
};

// -- Connect to unified header component events --------------------------------
// Listen for language changes from cuchi-header component
document.getElementById('cuchi-header')?.addEventListener('languagechange', e => {
    selectLanguage(e.detail.locale, i18n);
    retranslateCharts(window.i18n || i18n);
});

// Listen for status click from cuchi-header component
document.getElementById('cuchi-header')?.addEventListener('statusclick', () => {
    window.onStatusClick();
});

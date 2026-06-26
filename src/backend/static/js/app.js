// app.js - Main orchestrator. Wires all modules together.
import { fetchStatus, fetchSensors, fetchOutdoor, fetchErrors } from './services/api.js';
import { loadHistory, updateHistory }              from './services/sensorHistory.js';
import { updateAvgTemp, updateOutdoor, updateSensorsCount, updateSensorsDetail, openModal, closeModal } from './components/avgTemp.js';
import { updateAcState, editMode, editFanSpeed } from './components/acState.js';
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

// —— Overlay helpers (F0.33) ——————————————————————————————————————————
function showApp() {
    const overlay = document.getElementById('loading-overlay');
    const content = document.getElementById('app-content');
    if (content) content.classList.add('visible');
    if (overlay) {
        overlay.classList.add('fade-out');
        setTimeout(() => { overlay.style.display = 'none'; }, 450);
    }
}

// —— Init ————————————————————————————————————————————————————————————————————————————
(async function init() {
    // F0.33 — control the loading overlay.
    // Strategy: do NOT depend on window.i18nReady (race condition with classic scripts).
    // Instead, kick off i18n init ourselves and race it against a timeout.

    // 1. Start i18n if available, but never block forever on it
    const i18nPromise = (window.i18n && typeof window.i18n.init === 'function')
        ? window.i18n.init().catch(() => {})
        : Promise.resolve();
    await Promise.race([i18nPromise, new Promise(r => setTimeout(r, 4000))]);

    // Re-read i18n in case it loaded
    const resolvedI18n = window.i18n || { t: k => k };
    initCharts();
    initLanguageDropdown(resolvedI18n);

    // 2. Load history (optional, timeout 4s)
    try {
        await Promise.race([loadHistory(), new Promise(r => setTimeout(r, 4000))]);
    } catch { /* non-fatal */ }

    // 3. First data poll (timeout 6s)
    try {
        await Promise.race([poll(), new Promise(r => setTimeout(r, 6000))]);
    } catch { /* non-fatal */ }

    // 4. Always show the app — even if everything above failed
    showApp();
    setInterval(poll, 5000);
})();

// —— Global handlers (called from HTML onclick) ———————————————————————————————
window.openModal      = openModal;
window.closeModal     = closeModal;
window.changeTarget   = changeTarget;
window.setControlMode = mode => setControlMode(mode);
window.editMode       = () => editMode(i18n);
window.editFanSpeed   = () => editFanSpeed(i18n);
window.openErrorsModal  = () => { fetchErrors().then(d => openErrorsModal(d.errors || [], i18n)).catch(() => openErrorsModal([], i18n)); };
window.closeErrorsModal = closeErrorsModal;
// Clicking the status indicator opens errors modal only when there are errors
window.onStatusClick    = () => { fetchErrors().then(d => { if (d.has_errors) openErrorsModal(d.errors || [], i18n); }).catch(() => {}); };
window.toggleLanguageMenu = toggleLanguageMenu;
window.selectLanguage     = locale => selectLanguage(locale, i18n);

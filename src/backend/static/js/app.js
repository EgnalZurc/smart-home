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
        updateSensorsDetail(sensors, i18n, status.ac_real);

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

// ── Humidity Study Modal (HUM-0 - temporary) ─────────────────────────────────
window.showHumidityStudy = async function() {
    const modal = document.getElementById('humidity-modal');
    const content = document.getElementById('humidity-study-content');
    modal.classList.remove('hidden');
    requestAnimationFrame(() => modal.classList.add('modal-visible'));

    content.innerHTML = '<p class="text-slate-400 text-sm text-center py-4">Loading\u2026</p>';
    try {
        const r = await fetch('/api/humidity/study');
        const d = await r.json();
        content.innerHTML = _renderHumidityStudy(d);
    } catch (e) {
        content.innerHTML = '<p class="text-red-400 text-sm text-center py-4">Error loading data</p>';
    }
};

window.closeHumidityModal = function() {
    const modal = document.getElementById('humidity-modal');
    modal.classList.remove('modal-visible');
    setTimeout(() => modal.classList.add('hidden'), 300);
};

function _renderHumidityStudy(d) {
    if (d.status === 'no_data') {
        return `<p class="text-slate-400 text-sm text-center py-4">${d.message}</p>`;
    }

    const recColor = d.recommendation.includes('HUMIDIFIER')
        ? '#f87171' : d.recommendation.includes('Monitor')
        ? '#fbbf24' : '#4ade80';

    const rows = (d.snapshots || []).slice().reverse().map(s => {
        const sig = s.humidifier_needed_signal
            ? '<span class="text-red-400">\u26a0\ufe0f YES</span>'
            : '<span class="text-slate-500">no</span>';
        const below = (s.fraction_below_40 * 100).toFixed(0) + '%';
        const belowColor = s.fraction_below_40 > 0.65 ? '#f87171'
                         : s.fraction_below_40 > 0.5  ? '#fbbf24' : '#64748b';
        return `<div class="bg-slate-900/40 rounded-xl px-3 py-2 border border-slate-700/30">
            <div class="flex justify-between items-center">
                <span class="text-xs font-medium text-slate-300">${s.date}</span>
                <span class="text-[10px]">${sig}</span>
            </div>
            <div class="flex gap-4 mt-1 text-[10px] text-slate-400">
                <span>Mean: <strong class="text-white">${s.mean}%</strong></span>
                <span>Min: ${s.min}%</span>
                <span>Max: ${s.max}%</span>
                <span style="color:${belowColor}">&lt;40%: ${below}</span>
            </div>
        </div>`;
    }).join('');

    return `
        <div class="bg-slate-900/50 rounded-xl p-3 border border-slate-700/30 mb-3">
            <div class="flex justify-between items-center mb-2">
                <span class="text-[10px] text-slate-400 uppercase tracking-wider">Study progress</span>
                <span class="text-xs text-slate-300">${d.days_collected} / ${d.study_duration_days} days</span>
            </div>
            <div class="w-full bg-slate-700/40 rounded-full h-1.5 mb-3">
                <div class="h-1.5 rounded-full bg-blue-500" style="width:${Math.min(100, d.days_collected / d.study_duration_days * 100).toFixed(0)}%"></div>
            </div>
            <div class="grid grid-cols-3 gap-2 text-center">
                <div><p class="text-[9px] text-slate-500 uppercase">Avg mean</p>
                     <p class="text-sm font-bold text-white">${d.overall_mean}%</p></div>
                <div><p class="text-[9px] text-slate-500 uppercase">Below 40% avg</p>
                     <p class="text-sm font-bold" style="color:${d.avg_fraction_below_40 > 0.6 ? '#f87171' : '#fbbf24'}">${(d.avg_fraction_below_40 * 100).toFixed(0)}%</p></div>
                <div><p class="text-[9px] text-slate-500 uppercase">Signal days</p>
                     <p class="text-sm font-bold text-white">${d.days_signal_yes} / ${d.days_collected}</p></div>
            </div>
        </div>
        <div class="rounded-xl px-3 py-2.5 mb-3 text-center border" style="border-color:${recColor}33;background:${recColor}11">
            <p class="text-[10px] text-slate-400 uppercase tracking-wider mb-0.5">Recommendation</p>
            <p class="text-sm font-bold" style="color:${recColor}">${d.recommendation}</p>
        </div>
        <p class="text-[10px] text-slate-500 uppercase tracking-wider mb-2">Daily snapshots</p>
        <div class="space-y-2">${rows}</div>`;
}

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

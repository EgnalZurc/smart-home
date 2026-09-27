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

// Humidity Study Modal (HUM-0 - temporary)
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

    const REC_COLOR  = { recommended: '#f87171', not_needed: '#4ade80', insufficient_data: '#fbbf24', no_data: '#64748b' };
    const REC_LABEL_ES = { recommended: 'Se recomienda humificador', not_needed: 'No necesario', insufficient_data: 'Datos insuficientes', no_data: 'Sin datos' };
    const SEASON_ICON  = { spring: '??', summer: '??', autumn: '??', winter: '??' };
    const SEASON_ORDER = ['spring', 'summer', 'autumn', 'winter'];

    const seasonCards = SEASON_ORDER.map(key => {
        const s = d.seasons[key];
        if (!s) return '';
        const color = REC_COLOR[s.recommendation] || '#64748b';
        const label = REC_LABEL_ES[s.recommendation] || s.recommendation;
        const icon  = SEASON_ICON[key] || '';
        const meanStr  = s.mean !== null ? s.mean.toFixed(1) + '%' : '?';
        const fracStr  = s.avg_fraction_below_40 !== null ? (s.avg_fraction_below_40 * 100).toFixed(0) + '%' : '?';
        const daysStr  = s.days > 0 ? `${s.days_signal}/${s.days} d` : '?';
        return `<div class="bg-slate-900/50 rounded-2xl p-3 border" style="border-color:${color}33">
            <div class="flex items-center justify-between mb-2">
                <span class="text-sm font-semibold">${icon} ${s.name_es}</span>
                <span class="text-[10px] font-medium px-2 py-0.5 rounded-full" style="color:${color};background:${color}1a">${label}</span>
            </div>
            <div class="grid grid-cols-3 gap-1 text-center">
                <div><p class="text-[9px] text-slate-500 uppercase">Media</p>
                     <p class="text-sm font-bold text-white">${meanStr}</p></div>
                <div><p class="text-[9px] text-slate-500 uppercase">&lt;40%</p>
                     <p class="text-sm font-bold" style="color:${s.avg_fraction_below_40 > 0.5 ? '#f87171' : '#94a3b8'}">${fracStr}</p></div>
                <div><p class="text-[9px] text-slate-500 uppercase">Se?al</p>
                     <p class="text-sm font-bold text-white">${daysStr}</p></div>
            </div>
        </div>`;
    }).join('');

    // Recent daily snapshots (last 14)
    const recent = (d.snapshots || []).slice().reverse().slice(0, 14);
    const rows = recent.map(s => {
        const sig = s.humidifier_needed_signal
            ? '<span style="color:#f87171">?? s?</span>'
            : '<span style="color:#475569">no</span>';
        const below = (s.fraction_below_40 * 100).toFixed(0) + '%';
        const belowColor = s.fraction_below_40 > 0.65 ? '#f87171' : s.fraction_below_40 > 0.5 ? '#fbbf24' : '#64748b';
        const seasonIcon = { spring:'??', summer:'??', autumn:'??', winter:'??' }[s.season] || '';
        return `<div class="bg-slate-900/40 rounded-xl px-3 py-2 border border-slate-700/30">
            <div class="flex justify-between items-center">
                <span class="text-xs text-slate-300">${seasonIcon} ${s.date}</span>
                <span class="text-[10px]">${sig}</span>
            </div>
            <div class="flex gap-3 mt-1 text-[10px] text-slate-400 flex-wrap">
                <span>Media: <strong class="text-white">${s.mean}%</strong></span>
                <span>Min: ${s.min}%</span>
                <span>Max: ${s.max}%</span>
                <span style="color:${belowColor}">&lt;40%: ${below}</span>
            </div>
        </div>`;
    }).join('');

    return `
        <div class="flex items-center justify-between mb-3">
            <p class="text-[10px] text-slate-500 uppercase tracking-wider">An?lisis estacional</p>
            <p class="text-[10px] text-slate-500">${d.total_days} d?as registrados</p>
        </div>
        <div class="space-y-2 mb-4">${seasonCards}</div>
        <p class="text-[10px] text-slate-500 uppercase tracking-wider mb-2">?ltimos d?as</p>
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
window.onStatusClick    = () => { fetchErrors().then(d => { if (d.has_errors) openErrorsModal(d.errors || [], i18n); }).catch(() => {}); };
window.toggleLanguageMenu = toggleLanguageMenu;
window.selectLanguage     = locale => {
    selectLanguage(locale, i18n);
    retranslateCharts(window.i18n || i18n);
};

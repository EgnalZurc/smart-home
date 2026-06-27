// charts.js ? Dynamic single chart with multiselect sources + time range picker
import { fetchSensorHistoryRange } from '../services/sensorHistory.js';
import { SENSOR_COLORS } from '../utils/colors.js';

// ?? State ?????????????????????????????????????????????????????????????????????
let _chart      = null;     // Chart.js instance
let _sensors    = [];       // [{name, color}]
let _i18n       = null;
let _rangeHours = 24;       // default: last 24h
let _selTemp    = null;     // Set of selected sensor names for temperature
let _selHum     = null;     // Set of selected sensor names for humidity
let _activeTab  = 'temp';   // 'temp' | 'hum'

// ?? Range options ?????????????????????????????????????????????????????????????
const RANGES = [
    { key: 'range1h',  hours: 1  },
    { key: 'range6h',  hours: 6  },
    { key: 'range12h', hours: 12 },
    { key: 'range24h', hours: 24 },
    { key: 'range48h', hours: 48 },
    { key: 'range7d',  hours: 168 },
];

// ?? Init ??????????????????????????????????????????????????????????????????????
export function initCharts(i18n) {
    _i18n = i18n;
    const ctx = document.getElementById('chart-dynamic');
    if (!ctx) return;
    _chart = new Chart(ctx.getContext('2d'), {
        type: 'line',
        data: { datasets: [] },
        options: _chartOptions(),
    });
    _renderRangePicker();
}

// ?? Called from app.js on each poll with current sensor list ??????????????????
export function setSensors(sensors) {
    const names = sensors.map(s => s.name);
    _sensors = sensors.map((s, i) => ({ name: s.name, color: SENSOR_COLORS[i % SENSOR_COLORS.length] }));

    // Init selections to "all" on first call
    if (_selTemp === null) _selTemp = new Set(names);
    if (_selHum  === null) _selHum  = new Set(names);

    // Remove any sensor that no longer exists
    for (const n of [..._selTemp]) { if (!names.includes(n)) _selTemp.delete(n); }
    for (const n of [..._selHum])  { if (!names.includes(n)) _selHum.delete(n);  }

    _renderSourceDropdowns();
}

// ?? Public: refresh chart data (called from app.js after poll) ????????????????
export async function refreshChart() {
    if (!_chart) return;
    await _loadAndRender();
}

// ?? Data loading ??????????????????????????????????????????????????????????????
async function _loadAndRender() {
    const nowSec  = Date.now() / 1000;
    const startSec = nowSec - _rangeHours * 3600;
    const field   = _activeTab;
    const sel     = field === 'temp' ? _selTemp : _selHum;

    let rawData;
    try {
        rawData = await fetchSensorHistoryRange(startSec, nowSec);
    } catch {
        return;
    }

    // Build one dataset per selected sensor
    const datasets = [];
    for (const sensor of _sensors) {
        if (!sel.has(sensor.name)) continue;
        const readings = (rawData[sensor.name] || []).filter(r => r.ts >= startSec * 1000);
        if (!readings.length) continue;

        // Bucket + smooth
        const pts = _buildPoints(readings, field, _bucketMinutes(_rangeHours));
        const smoothed = _smooth(pts.map(p => p.value), 2);

        datasets.push({
            label: sensor.name,
            data: smoothed,
            borderColor: sensor.color,
            backgroundColor: sensor.color + '18',
            borderWidth: 1.5,
            tension: 0.4,
            pointRadius: 0,
            pointHoverRadius: 5,
            pointHoverBackgroundColor: sensor.color,
            fill: false,
            spanGaps: false,
        });
    }

    const labels = datasets.length > 0
        ? _buildLabels(rawData, [...sel], field, startSec * 1000, _bucketMinutes(_rangeHours))
        : [];

    const noDataEl = document.getElementById('chart-no-data');
    if (datasets.length === 0 || labels.length === 0) {
        if (noDataEl) noDataEl.classList.remove('hidden');
        _chart.data = { labels: [], datasets: [] };
        _chart.update('none');
        return;
    }
    if (noDataEl) noDataEl.classList.add('hidden');

    // Align all datasets to the same label array
    const isHum = field === 'hum';
    _chart.options = _chartOptions(isHum ? v => v + '%' : v => v + '\u00b0C');
    _chart.data.labels   = labels;
    _chart.data.datasets = datasets;
    _chart.update('none');
}

// ?? Build shared label array from all selected sensors ????????????????????????
function _buildLabels(rawData, selectedNames, field, startMs, bucketMin) {
    const bucketMs = bucketMin * 60 * 1000;
    const buckets  = new Set();
    for (const name of selectedNames) {
        (rawData[name] || [])
            .filter(r => r.ts >= startMs)
            .forEach(r => buckets.add(Math.floor(r.ts / bucketMs) * bucketMs));
    }
    return [...buckets].sort((a, b) => a - b).map(ts => _formatLabel(ts + bucketMs / 2));
}

// ?? Build averaged bucket points for one sensor ???????????????????????????????
function _buildPoints(readings, field, bucketMin) {
    const bucketMs = bucketMin * 60 * 1000;
    const buckets  = {};
    for (const r of readings) {
        const v = field === 'temp' ? r.temp : r.hum;
        if (v === null || v === undefined) continue;
        const key = Math.floor(r.ts / bucketMs) * bucketMs;
        if (!buckets[key]) buckets[key] = [];
        buckets[key].push(v);
    }
    return Object.entries(buckets)
        .sort(([a], [b]) => a - b)
        .map(([ts, vals]) => ({
            ts: parseInt(ts) + bucketMs / 2,
            value: Math.round((vals.reduce((s, v) => s + v, 0) / vals.length) * 10) / 10,
        }));
}

function _bucketMinutes(hours) {
    if (hours <= 1)   return 2;
    if (hours <= 6)   return 10;
    if (hours <= 12)  return 15;
    if (hours <= 24)  return 20;
    if (hours <= 48)  return 30;
    return 60;
}

// ?? Gaussian smoothing ????????????????????????????????????????????????????????
function _smooth(data, passes = 2) {
    if (data.length < 5) return data;
    const weights = [0.06, 0.24, 0.40, 0.24, 0.06];
    let result = [...data];
    for (let p = 0; p < passes; p++) {
        const s = [...result];
        for (let i = 2; i < result.length - 2; i++) {
            if (result[i] === null) continue;
            const w = [result[i-2], result[i-1], result[i], result[i+1], result[i+2]];
            if (w.some(v => v === null)) continue;
            s[i] = Math.round(w.reduce((sum, v, idx) => sum + v * weights[idx], 0) * 10) / 10;
        }
        result = s;
    }
    return result;
}

// ?? Label formatter ???????????????????????????????????????????????????????????
function _formatLabel(tsMs) {
    const d   = new Date(tsMs);
    const now = new Date();
    const sameDay = d.getDate() === now.getDate() && d.getMonth() === now.getMonth() && d.getFullYear() === now.getFullYear();
    const hhmm = d.toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit' });
    if (sameDay) return hhmm;
    return d.toLocaleDateString('es-ES', { day: '2-digit', month: '2-digit' }) + ' ' + hhmm;
}

// ?? Chart.js options ??????????????????????????????????????????????????????????
function _chartOptions(tickCb = null) {
    return {
        responsive: true,
        animation: false,
        interaction: { mode: 'nearest', intersect: false },
        scales: {
            y: {
                grid: { color: 'rgba(148,163,184,0.06)' },
                ticks: {
                    color: '#64748b', font: { size: 10 }, maxTicksLimit: 5,
                    callback: tickCb || undefined, padding: 4,
                },
                afterDataLimits(scale) {
                    const range = scale.max - scale.min;
                    const pad = range * 0.15 || 0.3;
                    scale.max += pad; scale.min -= pad;
                },
            },
            x: {
                grid: { display: false },
                ticks: { color: '#475569', font: { size: 8 }, maxTicksLimit: 6, maxRotation: 0 },
            },
        },
        plugins: {
            legend: {
                display: true,
                labels: { color: '#94a3b8', font: { size: 10 }, boxWidth: 10, padding: 10, usePointStyle: true },
            },
            tooltip: {
                backgroundColor: 'rgba(15,23,42,0.95)',
                borderColor: 'rgba(100,116,139,0.4)',
                borderWidth: 1,
                titleColor: '#94a3b8',
                bodyColor: '#e2e8f0',
                padding: 10,
                cornerRadius: 8,
            },
        },
    };
}

// ?? UI: range picker ??????????????????????????????????????????????????????????
function _renderRangePicker() {
    const el = document.getElementById('chart-range-picker');
    if (!el) return;
    el.innerHTML = RANGES.map(r => `
        <button
            data-hours="${r.hours}"
            onclick="chartSetRange(${r.hours})"
            class="chart-range-btn px-2.5 py-1 rounded-lg text-[10px] font-medium transition-all border
                   ${r.hours === _rangeHours
                       ? 'bg-blue-600/30 border-blue-500/60 text-blue-300'
                       : 'bg-slate-800/60 border-slate-700/40 text-slate-400 hover:border-slate-600'}"
        >${_i18n ? _i18n.t('chart.' + r.key) : r.hours + 'h'}</button>
    `).join('');
}

function _renderSourceDropdowns() {
    _renderOneDropdown('temp');
    _renderOneDropdown('hum');
}

function _renderOneDropdown(field) {
    const el = document.getElementById('chart-sources-' + field);
    if (!el) return;
    const sel = field === 'temp' ? _selTemp : _selHum;
    el.innerHTML = _sensors.map(s => {
        const checked = sel.has(s.name);
        return `<label class="flex items-center gap-2 px-3 py-2 rounded-lg cursor-pointer hover:bg-slate-700/40 transition-colors select-none">
            <input type="checkbox" value="${s.name}" data-field="${field}"
                   ${checked ? 'checked' : ''}
                   onchange="chartToggleSource('${field}','${s.name}',this.checked)"
                   class="w-3.5 h-3.5 rounded accent-blue-500 cursor-pointer">
            <span class="w-2 h-2 rounded-full flex-shrink-0" style="background:${s.color}"></span>
            <span class="text-xs text-slate-300">${s.name}</span>
        </label>`;
    }).join('');
}

// ?? Tab switching ?????????????????????????????????????????????????????????????
function _renderTabs() {
    const t = document.getElementById('chart-tab-temp');
    const h = document.getElementById('chart-tab-hum');
    if (!t || !h) return;
    const activeClass   = 'border-b-2 border-blue-400 text-blue-300';
    const inactiveClass = 'border-b-2 border-transparent text-slate-500';
    t.className = 'flex-1 py-2 text-[11px] font-medium text-center transition-all cursor-pointer ' +
                  (_activeTab === 'temp' ? activeClass : inactiveClass);
    h.className = 'flex-1 py-2 text-[11px] font-medium text-center transition-all cursor-pointer ' +
                  (_activeTab === 'hum'  ? activeClass : inactiveClass);

    // Show/hide source dropdowns
    const tempSrc = document.getElementById('chart-sources-temp-wrap');
    const humSrc  = document.getElementById('chart-sources-hum-wrap');
    if (tempSrc) tempSrc.classList.toggle('hidden', _activeTab !== 'temp');
    if (humSrc)  humSrc.classList.toggle('hidden',  _activeTab !== 'hum');
}

// ?? Global handlers (called from HTML) ???????????????????????????????????????
window.chartSetRange = function(hours) {
    _rangeHours = hours;
    _renderRangePicker();
    _loadAndRender();
};

window.chartToggleSource = function(field, name, checked) {
    const sel = field === 'temp' ? _selTemp : _selHum;
    if (checked) sel.add(name); else sel.delete(name);
    _loadAndRender();
};

window.chartSetTab = function(tab) {
    _activeTab = tab;
    _renderTabs();
    _loadAndRender();
};

// ?? Re-translate (called when language changes) ???????????????????????????????
export function retranslateCharts(i18n) {
    _i18n = i18n;
    _renderRangePicker();
    _renderTabs();
}

// Render tabs on init (called after DOM is ready)
export function initChartTabs() {
    _renderTabs();
}

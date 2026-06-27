// charts.js - Dynamic chart: average + individual sensors + A/C temp
import { fetchSensorHistoryRange } from '../services/sensorHistory.js';
import { SENSOR_COLORS } from '../utils/colors.js';

// ?? State ?????????????????????????????????????????????????????????????????????
let _chart      = null;
let _sensors    = [];       // [{name, color}]
let _acRoomTemp = null;     // latest A/C room temp (number | null)
let _i18n       = null;
let _rangeHours = 24;
let _activeTab  = 'temp';  // 'temp' | 'hum'

// Which series are visible: 'avg' always default-on, sensors default-off
// Stored as Set of keys: 'avg', 'ac', or sensor name
let _visibleTemp = new Set(['avg']);
let _visibleHum  = new Set(['avg']);

// ?? Range options ?????????????????????????????????????????????????????????????
const RANGES = [
    { key: 'range1h',  hours: 1   },
    { key: 'range6h',  hours: 6   },
    { key: 'range12h', hours: 12  },
    { key: 'range24h', hours: 24  },
    { key: 'range48h', hours: 48  },
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

export function initChartTabs() {
    _renderTabs();
}

// ?? Called from app.js on each poll ??????????????????????????????????????????
export function setSensors(sensors, acRoomTemp) {
    _acRoomTemp = acRoomTemp ?? null;
    const names = sensors.map(s => s.name);
    _sensors = sensors.map((s, i) => ({ name: s.name, color: SENSOR_COLORS[i % SENSOR_COLORS.length] }));

    // Clean up visibility sets if sensors changed
    for (const n of [..._visibleTemp]) { if (n !== 'avg' && n !== 'ac' && !names.includes(n)) _visibleTemp.delete(n); }
    for (const n of [..._visibleHum])  { if (n !== 'avg' && !names.includes(n)) _visibleHum.delete(n); }

    _renderLegend();
}

export async function refreshChart() {
    if (!_chart) return;
    await _loadAndRender();
}

// ?? Data loading + render ?????????????????????????????????????????????????????
async function _loadAndRender() {
    const nowSec   = Date.now() / 1000;
    const startSec = nowSec - _rangeHours * 3600;
    const isHum    = _activeTab === 'hum';
    const field    = isHum ? 'hum' : 'temp';
    const visible  = isHum ? _visibleHum : _visibleTemp;
    const bMin     = _bucketMinutes(_rangeHours);
    const bMs      = bMin * 60 * 1000;

    let rawData;
    try { rawData = await fetchSensorHistoryRange(startSec, nowSec); }
    catch { return; }

    // ?? Build bucket map: ts -> { sensorName: [values] } ?????????????????????
    const bucketMap = {};  // key=bucketTs, value={ name: [vals] }
    for (const sensor of _sensors) {
        for (const r of (rawData[sensor.name] || [])) {
            if (r.ts < startSec * 1000) continue;
            const v = isHum ? r.hum : r.temp;
            if (v === null || v === undefined) continue;
            const bk = Math.floor(r.ts / bMs) * bMs;
            if (!bucketMap[bk]) bucketMap[bk] = {};
            if (!bucketMap[bk][sensor.name]) bucketMap[bk][sensor.name] = [];
            bucketMap[bk][sensor.name].push(v);
        }
    }

    const sortedBuckets = Object.keys(bucketMap).map(Number).sort((a, b) => a - b);
    if (sortedBuckets.length === 0) {
        const noDataEl = document.getElementById('chart-no-data');
        if (noDataEl) noDataEl.classList.remove('hidden');
        _chart.data = { labels: [], datasets: [] };
        _chart.update('none');
        return;
    }
    document.getElementById('chart-no-data')?.classList.add('hidden');

    const labels = sortedBuckets.map(bk => _formatLabel(bk + bMs / 2));

    // ?? Average dataset ???????????????????????????????????????????????????????
    const avgValues = sortedBuckets.map(bk => {
        const allVals = Object.values(bucketMap[bk]).flat();
        return allVals.length ? Math.round((allVals.reduce((s, v) => s + v, 0) / allVals.length) * 10) / 10 : null;
    });

    const datasets = [];

    if (visible.has('avg')) {
        datasets.push({
            label: _t('chart.average'),
            data: _smooth(avgValues, 2),
            borderColor: 'rgba(255,255,255,0.85)',
            backgroundColor: 'rgba(255,255,255,0.05)',
            borderWidth: 2,
            tension: 0.4,
            pointRadius: 0,
            pointHoverRadius: 5,
            pointHoverBackgroundColor: '#ffffff',
            fill: { target: 'origin', above: 'rgba(255,255,255,0.04)' },
            spanGaps: true,
            order: 0,
        });
    }

    // -- A/C room temp dataset (temp tab only, from hourly history) -----------
    if (!isHum && visible.has('ac')) {
        const acReadings = (rawData['AC'] || []).filter(r => r.ts >= startSec * 1000);
        if (acReadings.length > 0) {
            const acPts = _buildAcPoints(acReadings, bMin);
            const acValues = sortedBuckets.map(bk => {
                const nearest = acPts.find(p => Math.abs(p.bk - bk) < bMs);
                return nearest ? nearest.value : null;
            });
            if (acValues.some(v => v !== null)) {
                datasets.push({
                    label: 'A/C',
                    data: acValues,
                    borderColor: 'rgba(148,163,184,0.7)',
                    backgroundColor: 'transparent',
                    borderWidth: 1.5,
                    borderDash: [5, 4],
                    tension: 0.3,
                    pointRadius: 0,
                    pointHoverRadius: 4,
                    pointHoverBackgroundColor: 'rgba(148,163,184,0.9)',
                    fill: false,
                    spanGaps: true,
                    order: 1,
                });
            }
        } else if (_acRoomTemp !== null) {
            // Fallback: no history yet - flat reference line
            datasets.push({
                label: 'A/C',
                data: sortedBuckets.map(() => _acRoomTemp),
                borderColor: 'rgba(148,163,184,0.4)',
                backgroundColor: 'transparent',
                borderWidth: 1,
                borderDash: [4, 4],
                tension: 0,
                pointRadius: 0,
                pointHoverRadius: 0,
                fill: false,
                spanGaps: true,
                order: 1,
            });
        }
    }

    // ?? Individual sensor datasets ????????????????????????????????????????????
    for (const sensor of _sensors) {
        if (!visible.has(sensor.name)) continue;
        const values = sortedBuckets.map(bk => {
            const vals = bucketMap[bk]?.[sensor.name];
            return vals ? Math.round((vals.reduce((s, v) => s + v, 0) / vals.length) * 10) / 10 : null;
        });
        datasets.push({
            label: sensor.name,
            data: _smooth(values, 2),
            borderColor: sensor.color,
            backgroundColor: 'transparent',
            borderWidth: 1.5,
            tension: 0.4,
            pointRadius: 0,
            pointHoverRadius: 4,
            pointHoverBackgroundColor: sensor.color,
            fill: false,
            spanGaps: true,
            order: 2,
        });
    }

    _chart.options = _chartOptions(isHum ? v => v + '%' : v => v + '\u00b0C');
    _chart.data.labels   = labels;
    _chart.data.datasets = datasets;
    _chart.update('none');

    // Update mean values display
    _renderMeanValues(avgValues, isHum);
}

// ?? Mean values bar ???????????????????????????????????????????????????????????
function _renderMeanValues(avgValues, isHum) {
    const el = document.getElementById('chart-means');
    if (!el) return;
    const valid = avgValues.filter(v => v !== null);
    if (!valid.length) { el.innerHTML = ''; return; }
    const mean = Math.round((valid.reduce((s, v) => s + v, 0) / valid.length) * 10) / 10;
    const min  = Math.min(...valid);
    const max  = Math.max(...valid);
    const unit = isHum ? '%' : '\u00b0C';
    el.innerHTML = `
        <span class="text-[10px] text-slate-500">${_t('chart.mean')}: <strong class="text-slate-300">${mean}${unit}</strong></span>
        <span class="text-[10px] text-slate-600">\u2193 ${min}${unit}</span>
        <span class="text-[10px] text-slate-600">\u2191 ${max}${unit}</span>
    `;
}

// ?? Legend: toggle buttons ????????????????????????????????????????????????????
function _renderLegend() {
    const isHum   = _activeTab === 'hum';
    const visible = isHum ? _visibleHum : _visibleTemp;
    const el      = document.getElementById('chart-legend');
    if (!el) return;

    const items = [];
    items.push({ key: 'avg', label: _t('chart.average'), color: '#e2e8f0' });
    if (!isHum && _acRoomTemp !== null) {
        items.push({ key: 'ac', label: 'A/C', color: '#94a3b8' });
    }
    for (const s of _sensors) {
        items.push({ key: s.name, label: s.name, color: s.color });
    }

    el.innerHTML = items.map(item => {
        const on = visible.has(item.key);
        // Chip: active = colored dot + slight glow, inactive = muted dot + dimmed text
        return `<button
            onclick="chartToggleSeries('${item.key}')"
            style="
                display:inline-flex; align-items:center; gap:6px;
                padding:5px 10px 5px 7px;
                border-radius:999px;
                border:1px solid ${on ? item.color + '55' : 'rgba(71,85,105,0.4)'};
                background:${on ? item.color + '14' : 'rgba(15,23,42,0.4)'};
                color:${on ? item.color : '#475569'};
                font-size:10px; font-weight:500;
                cursor:pointer; user-select:none;
                transition:all 0.18s ease;
                white-space:nowrap;
                box-shadow:${on ? '0 0 8px ' + item.color + '22' : 'none'};
            "
            onmouseenter="this.style.opacity='0.85'"
            onmouseleave="this.style.opacity='1'"
        >
            <span style="
                width:8px; height:8px; border-radius:50%; flex-shrink:0;
                background:${on ? item.color : 'rgba(71,85,105,0.6)'};
                box-shadow:${on ? '0 0 6px ' + item.color + '88' : 'none'};
                transition:all 0.18s ease;
            "></span>
            ${item.label}
        </button>`;
    }).join('');
}

function _renderTabs() {
    const t = document.getElementById('chart-tab-temp');
    const h = document.getElementById('chart-tab-hum');
    if (!t || !h) return;
    const on  = 'border-b-2 border-blue-400 text-blue-300';
    const off = 'border-b-2 border-transparent text-slate-500';
    t.className = 'flex-1 py-2 text-[11px] font-medium text-center transition-all cursor-pointer ' + (_activeTab === 'temp' ? on : off);
    h.className = 'flex-1 py-2 text-[11px] font-medium text-center transition-all cursor-pointer ' + (_activeTab === 'hum'  ? on : off);
}

// ?? Range picker ??????????????????????????????????????????????????????????????

function _renderRangePicker() {
    const el = document.getElementById('chart-range-picker');
    if (!el) return;

    // Segmented control: single pill container, active item has floating selector
    const labels = RANGES.map(r => _i18n ? _i18n.t('chart.' + r.key) : r.hours + 'h');
    const activeIdx = RANGES.findIndex(r => r.hours === _rangeHours);

    el.innerHTML = `
        <div style="
            display:flex; align-items:center;
            background:rgba(15,23,42,0.7);
            border:1px solid rgba(51,65,85,0.6);
            border-radius:10px;
            padding:3px;
            gap:1px;
            width:100%;
        ">
            ${RANGES.map((r, i) => {
                const active = r.hours === _rangeHours;
                return `<button
                    onclick="chartSetRange(${r.hours})"
                    style="
                        flex:1;
                        padding:5px 0;
                        border-radius:7px;
                        border:none;
                        font-size:10px; font-weight:${active ? '600' : '400'};
                        cursor:pointer;
                        transition:all 0.18s ease;
                        white-space:nowrap;
                        background:${active ? 'rgba(59,130,246,0.25)' : 'transparent'};
                        color:${active ? '#93c5fd' : '#475569'};
                        box-shadow:${active ? 'inset 0 0 0 1px rgba(59,130,246,0.5)' : 'none'};
                    "
                >${labels[i]}</button>`;
            }).join('')}
        </div>`;
}

// ?? Global handlers ???????????????????????????????????????????????????????????
window.chartSetRange = function(hours) {
    _rangeHours = hours;
    _renderRangePicker();
    _loadAndRender();
};

window.chartSetTab = function(tab) {
    _activeTab = tab;
    _renderTabs();
    _renderLegend();
    _loadAndRender();
};

window.chartToggleSeries = function(key) {
    const visible = _activeTab === 'hum' ? _visibleHum : _visibleTemp;
    if (visible.has(key)) visible.delete(key); else visible.add(key);
    _renderLegend();
    _loadAndRender();
};

export function retranslateCharts(i18n) {
    _i18n = i18n;
    _renderRangePicker();
    _renderTabs();
    _renderLegend();
}

// ?? Helpers ???????????????????????????????????????????????????????????????????
function _t(key) { return _i18n ? _i18n.t(key) : key; }

function _buildAcPoints(readings, bucketMin) {
    const bucketMs = bucketMin * 60 * 1000;
    const buckets  = {};
    for (const r of readings) {
        if (r.temp === null || r.temp === undefined) continue;
        const bk = Math.floor(r.ts / bucketMs) * bucketMs;
        if (!buckets[bk]) buckets[bk] = [];
        buckets[bk].push(r.temp);
    }
    return Object.entries(buckets)
        .sort(([a], [b]) => a - b)
        .map(([bk, vals]) => ({
            bk: parseInt(bk),
            value: Math.round((vals.reduce((s, v) => s + v, 0) / vals.length) * 10) / 10,
        }));
}

function _bucketMinutes(hours) {
    if (hours <= 1)  return 2;
    if (hours <= 6)  return 10;
    if (hours <= 12) return 15;
    if (hours <= 24) return 20;
    if (hours <= 48) return 30;
    return 60;
}

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

function _formatLabel(tsMs) {
    const d   = new Date(tsMs);
    const now = new Date();
    const sameDay = d.getDate() === now.getDate() && d.getMonth() === now.getMonth() && d.getFullYear() === now.getFullYear();
    const hhmm = d.toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit' });
    if (sameDay) return hhmm;
    return d.toLocaleDateString('es-ES', { day: '2-digit', month: '2-digit' }) + ' ' + hhmm;
}

function _chartOptions(tickCb = null) {
    return {
        responsive: true,
        maintainAspectRatio: false,
        animation: false,
        interaction: { mode: 'nearest', intersect: false },
        scales: {
            y: {
                grid: { color: 'rgba(148,163,184,0.06)' },
                ticks: { color: '#64748b', font: { size: 10 }, maxTicksLimit: 5, callback: tickCb || undefined, padding: 4 },
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
            legend: { display: false },  // We render our own legend
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

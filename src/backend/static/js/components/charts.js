import { getChartData } from '../services/sensorHistory.js';

let chart    = null;
let chartHum = null;

// Shared chart options factory
function _chartOptions(yTickCallback = null) {
    return {
        responsive: true,
        animation: false,
        interaction: { mode: 'nearest', intersect: false },
        scales: {
            y: {
                grid: { color: 'rgba(148,163,184,0.06)' },
                ticks: {
                    color: '#64748b',
                    font: { size: 10 },
                    maxTicksLimit: 5,
                    callback: yTickCallback || undefined,
                    padding: 4,
                },
                afterDataLimits(scale) {
                    const range = scale.max - scale.min;
                    const pad = range * 0.12 || 0.3;
                    scale.max += pad;
                    scale.min -= pad;
                },
            },
            x: {
                grid: { display: false },
                ticks: {
                    color: '#475569',
                    font: { size: 8 },
                    maxTicksLimit: 6,
                    maxRotation: 0,
                },
            },
        },
        plugins: {
            legend: {
                labels: { color: '#94a3b8', font: { size: 10 }, boxWidth: 8, padding: 12 },
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

export function initCharts() {
    chart = new Chart(document.getElementById('chart').getContext('2d'), {
        type: 'line',
        data: { datasets: [] },
        options: _chartOptions(),
    });

    chartHum = new Chart(document.getElementById('chart-hum').getContext('2d'), {
        type: 'line',
        data: { datasets: [] },
        options: _chartOptions(v => v + '%'),
    });
}

export function updateTempChart(sensors, i18n) {
    _updateChart(chart, sensors, 'temp', i18n.t('chart.average'));
}

export function updateHumChart(sensors, i18n) {
    _updateChart(chartHum, sensors, 'hum', i18n.t('chart.average'));
}

function _formatLabel(timestampMs) {
    const d = new Date(timestampMs);
    const now = new Date();
    const sameDay = d.getDate() === now.getDate()
        && d.getMonth() === now.getMonth()
        && d.getFullYear() === now.getFullYear();
    const hhmm = d.toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit' });
    if (sameDay) return hhmm;
    const ddmm = d.toLocaleDateString('es-ES', { day: '2-digit', month: '2-digit' });
    return `${ddmm} ${hhmm}`;
}

// Downsample: group raw points into fixed-size time buckets and average them.
// This eliminates the horizontal plateaus caused by "last known value" fill.
// bucketMinutes: time window per bucket (default 30min)
function _downsample(rawPoints, bucketMinutes = 30) {
    if (!rawPoints.length) return [];
    const bucketMs = bucketMinutes * 60 * 1000;
    const buckets = {};

    for (const { ts, value } of rawPoints) {
        if (value === null || value === undefined) continue;
        const key = Math.floor(ts / bucketMs) * bucketMs;
        if (!buckets[key]) buckets[key] = [];
        buckets[key].push(value);
    }

    return Object.entries(buckets)
        .sort(([a], [b]) => a - b)
        .map(([ts, vals]) => ({
            ts: parseInt(ts) + bucketMs / 2,  // center of bucket for label
            value: Math.round((vals.reduce((s, v) => s + v, 0) / vals.length) * 10) / 10,
        }));
}

function _updateChart(instance, sensors, field, avgLabel) {
    const chartData = getChartData(field);

    // Build per-sensor raw points and combine
    const allRaw = [];
    sensors.forEach(s => {
        (chartData[s.name] || []).forEach(p => {
            if (p.value !== null) allRaw.push(p);
        });
    });

    if (!allRaw.length) return;

    // For each time bucket, compute the real average across all sensors
    const bucketMs = 30 * 60 * 1000;
    const buckets = {};
    allRaw.forEach(({ ts, value }) => {
        const key = Math.floor(ts / bucketMs) * bucketMs;
        if (!buckets[key]) buckets[key] = [];
        buckets[key].push(value);
    });

    const points = Object.entries(buckets)
        .sort(([a], [b]) => a - b)
        .map(([ts, vals]) => ({
            ts: parseInt(ts) + bucketMs / 2,
            value: Math.round((vals.reduce((s, v) => s + v, 0) / vals.length) * 10) / 10,
        }));

    instance.data.labels = points.map(p => _formatLabel(p.ts));

    if (instance.data.datasets.length !== 1) {
        instance.data.datasets = [{
            label: avgLabel,
            data: [],
            borderColor: 'rgba(255,255,255,0.9)',
            borderWidth: 2,
            tension: 0.4,
            cubicInterpolationMode: 'monotone',
            pointRadius: 0,
            pointHoverRadius: 5,
            pointHoverBackgroundColor: '#ffffff',
            fill: {
                target: 'origin',
                above: 'rgba(255,255,255,0.04)',
            },
            spanGaps: false,
        }];
    } else {
        instance.data.datasets[0].label = avgLabel;
    }

    instance.data.datasets[0].data = points.map(p => p.value);
    instance.update('none');
}

import { getChartData } from '../services/sensorHistory.js';

let chart    = null;
let chartHum = null;

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
                    const pad = range * 0.15 || 0.3;
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

// Gaussian-weighted smoothing: replaces each point with a weighted average
// of its neighbours. Window=5, stronger center weight.
// This blends adjacent points even when values are identical, creating
// natural smooth transitions instead of hard steps.
function _smooth(data, passes = 2) {
    if (data.length < 5) return data;
    let result = [...data];
    const weights = [0.06, 0.24, 0.40, 0.24, 0.06]; // Gaussian kernel (sums to 1)
    for (let pass = 0; pass < passes; pass++) {
        const smoothed = [...result];
        for (let i = 2; i < result.length - 2; i++) {
            if (result[i] === null) continue;
            // Only smooth if all neighbours are non-null
            const w = [result[i-2], result[i-1], result[i], result[i+1], result[i+2]];
            if (w.some(v => v === null)) continue;
            smoothed[i] = Math.round(
                w.reduce((sum, v, idx) => sum + v * weights[idx], 0) * 10
            ) / 10;
        }
        result = smoothed;
    }
    return result;
}

// Group points into time buckets and average, then smooth.
// bucketMinutes controls granularity — smaller = more detail but more steps.
function _buildAveragedPoints(sensors, field, bucketMinutes = 20) {
    const chartData = getChartData(field);
    const bucketMs = bucketMinutes * 60 * 1000;
    const buckets = {};

    sensors.forEach(s => {
        (chartData[s.name] || []).forEach(({ ts, value }) => {
            if (value === null) return;
            const key = Math.floor(ts / bucketMs) * bucketMs;
            if (!buckets[key]) buckets[key] = [];
            buckets[key].push(value);
        });
    });

    const points = Object.entries(buckets)
        .sort(([a], [b]) => a - b)
        .map(([ts, vals]) => ({
            ts: parseInt(ts) + bucketMs / 2,
            value: Math.round((vals.reduce((s, v) => s + v, 0) / vals.length) * 10) / 10,
        }));

    return points;
}

function _updateChart(instance, sensors, field, avgLabel) {
    const points = _buildAveragedPoints(sensors, field, 20);
    if (!points.length) return;

    // Apply Gaussian smoothing to the values
    const smoothedValues = _smooth(points.map(p => p.value), 3);

    instance.data.labels = points.map(p => _formatLabel(p.ts));

    if (instance.data.datasets.length !== 1) {
        instance.data.datasets = [{
            label: avgLabel,
            data: [],
            borderColor: 'rgba(255,255,255,0.9)',
            borderWidth: 2,
            // cubicInterpolationMode: 'default' (not monotone) + high tension
            // produces smooth bezier curves between ALL points, even flat ones
            tension: 0.5,
            pointRadius: 0,
            pointHoverRadius: 5,
            pointHoverBackgroundColor: '#ffffff',
            fill: {
                target: 'origin',
                above: 'rgba(255,255,255,0.05)',
            },
            spanGaps: false,
        }];
    } else {
        instance.data.datasets[0].label = avgLabel;
    }

    instance.data.datasets[0].data = smoothedValues;
    instance.update('none');
}

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
                // Add padding so the line doesn't clip the top/bottom
                afterDataLimits(scale) {
                    const range = scale.max - scale.min;
                    const pad = range * 0.08 || 0.2;
                    scale.max += pad;
                    scale.min -= pad;
                },
            },
            x: {
                grid: { display: false },
                ticks: {
                    color: '#475569',
                    font: { size: 8 },
                    maxTicksLimit: 7,
                    maxRotation: 0,
                },
            },
        },
        plugins: {
            legend: {
                labels: { color: '#94a3b8', font: { size: 10 }, boxWidth: 8, padding: 12 },
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

// Format a timestamp for the X axis label.
// Same day -> "HH:MM", different day -> "DD/MM HH:MM"
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

function _updateChart(instance, sensors, field, avgLabel) {
    const chartData = getChartData(field);

    // Collect all unique timestamps (as numbers) from all sensors
    const allTs = new Set();
    sensors.forEach(s => (chartData[s.name] || []).forEach(p => allTs.add(p.ts)));
    const sortedTs = [...allTs].sort((a, b) => a - b);
    if (!sortedTs.length) return;

    instance.data.labels = sortedTs.map(_formatLabel);

    if (instance.data.datasets.length !== 1) {
        instance.data.datasets = [{
            label: avgLabel,
            data: [],
            borderColor: '#ffffff',
            borderWidth: 1.5,
            tension: 0.4,
            cubicInterpolationMode: 'monotone',   // prevents artificial peaks
            pointRadius: 0,
            pointHoverRadius: 4,
            fill: false,
            spanGaps: true,
        }];
    } else {
        instance.data.datasets[0].label = avgLabel;
    }

    // Per-sensor value maps: ts -> value
    const perSensor = sensors.map(s => {
        const h = chartData[s.name] || [];
        const map = {};
        h.forEach(p => { map[p.ts] = p.value; });
        return sortedTs.map(t => map[t] !== undefined ? map[t] : null);
    });

    // Average: use last known value per sensor at each point
    instance.data.datasets[0].data = sortedTs.map((_, ti) => {
        const values = sensors.map((_, si) => {
            let last = null;
            for (let j = 0; j <= ti; j++) if (perSensor[si][j] !== null) last = perSensor[si][j];
            return last;
        }).filter(v => v !== null);
        return values.length
            ? Math.round((values.reduce((a, b) => a + b, 0) / values.length) * 10) / 10
            : null;
    });

    instance.update('none');  // 'none' skips animation for smoother live updates
}

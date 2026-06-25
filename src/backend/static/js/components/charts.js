import { getChartData } from '../services/sensorHistory.js';

let chart    = null;
let chartHum = null;

export function initCharts() {
    chart = new Chart(document.getElementById('chart').getContext('2d'), {
        type: 'line',
        data: { datasets: [] },
        options: {
            responsive: true, animation: false,
            interaction: { mode: 'nearest', intersect: false },
            scales: {
                y: { grid: { color: 'rgba(148,163,184,0.08)' }, ticks: { color: '#64748b', font: { size: 10 } } },
                x: { grid: { display: false }, ticks: { color: '#475569', font: { size: 8 }, maxTicksLimit: 6 } },
            },
            plugins: { legend: { labels: { color: '#94a3b8', font: { size: 10 }, boxWidth: 8, padding: 12 } } },
        },
    });

    chartHum = new Chart(document.getElementById('chart-hum').getContext('2d'), {
        type: 'line',
        data: { datasets: [] },
        options: {
            responsive: true, animation: false,
            interaction: { mode: 'nearest', intersect: false },
            scales: {
                y: { grid: { color: 'rgba(148,163,184,0.08)' }, ticks: { color: '#64748b', font: { size: 10 }, callback: v => v + '%' } },
                x: { grid: { display: false }, ticks: { color: '#475569', font: { size: 8 }, maxTicksLimit: 6 } },
            },
            plugins: { legend: { labels: { color: '#94a3b8', font: { size: 10 }, boxWidth: 8, padding: 12 } } },
        },
    });
}

export function updateTempChart(sensors, i18n) {
    _updateChart(chart, sensors, 'temp', i18n.t('chart.average'));
}

export function updateHumChart(sensors, i18n) {
    _updateChart(chartHum, sensors, 'hum', i18n.t('chart.average'));
}

function _updateChart(instance, sensors, field, avgLabel) {
    const chartData = getChartData(field);
    const allTimes = new Set();
    sensors.forEach(s => (chartData[s.name] || []).forEach(p => allTimes.add(p.time)));
    const sortedTimes = [...allTimes].sort();
    if (!sortedTimes.length) return;

    instance.data.labels = sortedTimes;

    if (instance.data.datasets.length !== 1) {
        instance.data.datasets = [{
            label: avgLabel,
            data: [],
            borderColor: '#ffffff',
            borderWidth: 2,
            tension: 0.4,
            pointRadius: 0,
            pointHoverRadius: 4,
            fill: false,
            spanGaps: true,
        }];
    }

    // Per-sensor data arrays (for computing rolling average)
    const perSensor = sensors.map(s => {
        const h = chartData[s.name] || [];
        const map = {};
        h.forEach(p => { map[p.time] = p.value; });
        return sortedTimes.map(t => map[t] !== undefined ? map[t] : null);
    });

    // Average using last-known value per sensor
    instance.data.datasets[0].data = sortedTimes.map((_, ti) => {
        const values = sensors.map((_, i) => {
            let last = null;
            for (let j = 0; j <= ti; j++) if (perSensor[i][j] !== null) last = perSensor[i][j];
            return last;
        }).filter(v => v !== null);
        return values.length
            ? Math.round((values.reduce((a, b) => a + b, 0) / values.length) * 10) / 10
            : null;
    });

    instance.update();
}

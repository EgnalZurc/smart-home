import { fetchSensorHistory } from './api.js';

const MAX_POINTS = 200;

// In-memory store: { sensorName: [{timestamp, temp, hum}] }
let data = {};
let lastTimestamp = 0;

export async function loadHistory() {
    const raw = await fetchSensorHistory();
    data = {};
    for (const [name, readings] of Object.entries(raw)) {
        data[name] = readings.map(r => ({ timestamp: r.timestamp, temp: r.temperature, hum: r.humidity }));
    }
    for (const readings of Object.values(data)) {
        for (const r of readings) {
            if (r.timestamp > lastTimestamp) lastTimestamp = r.timestamp;
        }
    }
}

export async function updateHistory() {
    if (!lastTimestamp) return;
    const raw = await fetchSensorHistory(lastTimestamp + 0.001);
    for (const [name, readings] of Object.entries(raw)) {
        if (!data[name]) data[name] = [];
        for (const r of readings) {
            if (!data[name].some(e => e.timestamp === r.timestamp)) {
                data[name].push({ timestamp: r.timestamp, temp: r.temperature, hum: r.humidity });
                if (r.timestamp > lastTimestamp) lastTimestamp = r.timestamp;
            }
        }
        if (data[name].length > MAX_POINTS) data[name] = data[name].slice(-MAX_POINTS);
    }
}

// Returns { sensorName: [{ts: number(ms), value: number}] } for a given field
// ts is epoch milliseconds — charts.js uses it to format labels smartly
export function getChartData(field) {
    const result = {};
    for (const [name, readings] of Object.entries(data)) {
        result[name] = readings.map(r => ({
            ts: r.timestamp * 1000,   // convert to ms for Date()
            value: r[field],
        }));
    }
    return result;
}

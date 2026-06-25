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
    // Track most recent timestamp
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

// Returns { sensorName: [{time: string, value: number}] } for a given field ('temp'|'hum')
export function getChartData(field) {
    const result = {};
    for (const [name, readings] of Object.entries(data)) {
        result[name] = readings.map(r => {
            const d = new Date(r.timestamp * 1000);
            const day   = d.getDate().toString().padStart(2, '0');
            const month = (d.getMonth() + 1).toString().padStart(2, '0');
            const time  = d.toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit' });
            return { time: `${day}/${month} ${time}`, value: r[field] };
        });
    }
    return result;
}

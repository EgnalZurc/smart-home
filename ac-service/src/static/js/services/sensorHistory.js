import { fetchSensorHistoryApi } from './api.js';

const MAX_POINTS = 200;

// In-memory store: { sensorName: [{timestamp, temp, hum}] }
let _data = {};
let _lastTimestamp = 0;

export async function loadHistory() {
    const raw = await fetchSensorHistoryApi();
    _data = {};
    for (const [name, readings] of Object.entries(raw)) {
        _data[name] = readings.map(r => ({ timestamp: r.timestamp, temp: r.temperature, hum: r.humidity }));
    }
    for (const readings of Object.values(_data)) {
        for (const r of readings) {
            if (r.timestamp > _lastTimestamp) _lastTimestamp = r.timestamp;
        }
    }
}

export async function updateHistory() {
    if (!_lastTimestamp) return;
    const raw = await fetchSensorHistoryApi(_lastTimestamp + 0.001);
    for (const [name, readings] of Object.entries(raw)) {
        if (!_data[name]) _data[name] = [];
        for (const r of readings) {
            if (!_data[name].some(e => e.timestamp === r.timestamp)) {
                _data[name].push({ timestamp: r.timestamp, temp: r.temperature, hum: r.humidity });
                if (r.timestamp > _lastTimestamp) _lastTimestamp = r.timestamp;
            }
        }
        if (_data[name].length > MAX_POINTS) _data[name] = _data[name].slice(-MAX_POINTS);
    }
}

// Fetch a specific time range directly from the API
// Returns { sensorName: [{ts: ms, temp, hum}] }
export async function fetchSensorHistoryRange(startSec, endSec) {
    const raw = await fetchSensorHistoryApi(startSec, endSec);
    const result = {};
    for (const [name, readings] of Object.entries(raw)) {
        result[name] = readings.map(r => ({
            ts: r.timestamp * 1000,
            temp: r.temperature,
            hum: r.humidity,
        }));
    }
    return result;
}

// Legacy: returns in-memory data as chart-compatible format
// { sensorName: [{ts: ms, value}] } for a given field
export function getChartData(field) {
    const result = {};
    for (const [name, readings] of Object.entries(_data)) {
        result[name] = readings.map(r => ({
            ts: r.timestamp * 1000,
            value: r[field],
        }));
    }
    return result;
}

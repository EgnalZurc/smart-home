// All backend API calls in one place
const BASE = '';

export async function fetchStatus() {
    const r = await fetch(`${BASE}/api/status`);
    return r.json();
}

export async function fetchSensors() {
    const r = await fetch(`${BASE}/api/sensors`);
    return r.json();
}

// Renamed to fetchSensorHistoryApi to avoid collision with sensorHistory.js exports
export async function fetchSensorHistoryApi(start = null, end = null) {
    const params = new URLSearchParams();
    if (start !== null) params.set('start', start);
    if (end   !== null) params.set('end',   end);
    const qs = params.toString();
    const r = await fetch(`${BASE}/api/sensors/history${qs ? '?' + qs : ''}`);
    return r.json();
}

export async function fetchOutdoor() {
    const r = await fetch(`${BASE}/api/outdoor`);
    return r.json();
}

export async function postConfig(targetTemperature) {
    const r = await fetch(`${BASE}/api/config`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ target_temperature: targetTemperature }),
    });
    if (!r.ok) throw new Error(`config failed: ${r.status}`);
    return r.json();
}

export async function postControlMode(mode) {
    const r = await fetch(`${BASE}/api/control_mode`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode }),
    });
    if (!r.ok) throw new Error(`control_mode failed: ${r.status}`);
    return r.json();
}

export async function postManualParam(param, value) {
    const r = await fetch(
        `${BASE}/api/manual_param?param=${param}&value=${encodeURIComponent(value)}`,
        { method: 'POST' }
    );
    if (!r.ok) throw new Error(`manual_param failed: ${r.status}`);
    return r.json();
}

export async function fetchErrors() {
    const r = await fetch(`${BASE}/api/errors`);
    return r.json();
}

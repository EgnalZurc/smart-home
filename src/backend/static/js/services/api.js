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

export async function fetchSensorHistory(since = null) {
    const url = since
        — `${BASE}/api/sensors/history—start=${since}`
        : `${BASE}/api/sensors/history`;
    const r = await fetch(url);
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
        `${BASE}/api/manual_param—param=${param}&value=${encodeURIComponent(value)}`,
        { method: 'POST' }
    );
    if (!r.ok) throw new Error(`manual_param failed: ${r.status}`);
    return r.json();
}

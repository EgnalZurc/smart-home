// All backend API calls in one place
const BASE = '';

/**
 * Wrapper around fetch that:
 * 1. Always includes credentials (cookies) for same-origin requests
 * 2. Detects auth redirects and shows a clear message instead of infinite loading
 * 3. Handles network errors gracefully
 */
async function authFetch(url, options = {}) {
    // Always include credentials to send session cookie
    const fetchOptions = {
        ...options,
        credentials: 'same-origin',
    };
    
    let r;
    try {
        r = await fetch(url, fetchOptions);
    } catch (err) {
        // Network error - throw with clear message
        throw new Error(`Network error: ${err.message}`);
    }
    
    // If we got redirected to the login page, fetch followed the redirect
    // and we got HTML instead of JSON. Detect this and inform the user.
    if (r.url.includes('/api/auth/login') || r.url.includes('/auth/login')) {
        // Show error in UI instead of redirect loop
        const error = new Error('Session expired - please refresh and log in again');
        error.name = 'AuthError';
        throw error;
    }
    
    // Check for auth errors that weren't redirects
    if (r.status === 401 || r.status === 403) {
        const error = new Error('Access denied');
        error.name = 'AuthError';
        throw error;
    }
    
    return r;
}

export async function fetchStatus() {
    const r = await authFetch(`${BASE}/api/ac/status`);
    return r.json();
}

export async function fetchSensors() {
    const r = await authFetch(`${BASE}/api/ac/sensors`);
    return r.json();
}

// Renamed to fetchSensorHistoryApi to avoid collision with sensorHistory.js exports
export async function fetchSensorHistoryApi(start = null, end = null) {
    const params = new URLSearchParams();
    if (start !== null) params.set('start', start);
    if (end   !== null) params.set('end',   end);
    const qs = params.toString();
    const r = await authFetch(`${BASE}/api/ac/sensors/history${qs ? '?' + qs : ''}`);
    return r.json();
}

export async function fetchOutdoor() {
    const r = await authFetch(`${BASE}/api/ac/outdoor`);
    return r.json();
}

export async function postConfig(targetTemperature) {
    const r = await authFetch(`${BASE}/api/ac/config`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ target_temperature: targetTemperature }),
    });
    if (!r.ok) throw new Error(`config failed: ${r.status}`);
    return r.json();
}

export async function postControlMode(mode) {
    const r = await authFetch(`${BASE}/api/ac/control`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode }),
    });
    if (!r.ok) throw new Error(`control failed: ${r.status}`);
    return r.json();
}

export async function postManualParam(param, value) {
    const r = await authFetch(
        `${BASE}/api/ac/manual/param?param=${param}&value=${encodeURIComponent(value)}`,
        { method: 'POST' }
    );
    if (!r.ok) throw new Error(`manual_param failed: ${r.status}`);
    return r.json();
}

export async function fetchErrors() {
    const r = await authFetch(`${BASE}/api/ac/errors`);
    return r.json();
}

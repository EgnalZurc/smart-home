// Color helpers based on temperature and humidity ranges (F0.10)
export function tempColor(t) {
    if (t === null || t === undefined) return '#64748b';
    if (t < 18)  return '#1e40af';
    if (t < 20)  return '#3b82f6';
    if (t <= 26) return '#22c55e';
    if (t <= 28) return '#f97316';
    return '#ef4444';
}

export function humColor(h) {
    if (h === null || h === undefined) return '#64748b';
    if (h < 30)  return '#1e40af';
    if (h < 40)  return '#3b82f6';
    if (h <= 60) return '#22c55e';
    if (h <= 70) return '#f97316';
    return '#ef4444';
}

export const SENSOR_COLORS = ['#60a5fa', '#4ade80', '#f87171', '#fbbf24', '#a78bfa'];

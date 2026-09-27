import { tempColor, humColor, SENSOR_COLORS } from '../utils/colors.js';

export function updateAvgTemp(status) {
    const el = document.getElementById('avg-temp');
    if (status.average_temperature !== null) {
        el.textContent   = status.average_temperature.toFixed(1) + '°C';
        el.style.color   = tempColor(status.average_temperature);
    } else {
        el.textContent   = '--°C';
        el.style.color   = '#64748b';
    }

    const humEl = document.getElementById('avg-hum');
    if (status.average_humidity !== null) {
        humEl.textContent = status.average_humidity.toFixed(0) + '%';
        humEl.style.color = humColor(status.average_humidity);
    } else {
        humEl.textContent = '--%';
    }
}

function _aqiColor(aqi) {
    if (aqi === null || aqi === undefined) return '#64748b';
    if (aqi <= 20)  return '#22c55e';
    if (aqi <= 40)  return '#84cc16';
    if (aqi <= 60)  return '#fbbf24';
    if (aqi <= 80)  return '#f97316';
    if (aqi <= 100) return '#ef4444';
    return '#dc2626';
}

function _aqiLabel(aqi, i18n) {
    if (aqi === null || aqi === undefined) return '';
    if (aqi <= 20)  return i18n.t('main.aqiGood');
    if (aqi <= 40)  return i18n.t('main.aqiFair');
    if (aqi <= 60)  return i18n.t('main.aqiModerate');
    if (aqi <= 80)  return i18n.t('main.aqiPoor');
    if (aqi <= 100) return i18n.t('main.aqiVeryPoor');
    return i18n.t('main.aqiHazardous');
}

export function updateOutdoor(out, i18n) {
    const el = document.getElementById('outdoor-line');
    if (out.temperature !== null) {
        const aqi = out.aqi ?? null;
        const aqiHtml = aqi !== null
            ? ` · <span style="color:${_aqiColor(aqi)}" title="EAQI ${aqi}">${_aqiLabel(aqi, i18n)} (${aqi})</span>`
            : '';
        el.innerHTML = `🌍 <span>${i18n.t('main.outdoor')}</span>: `
            + `<span style="color:${tempColor(out.temperature)}">${out.temperature.toFixed(1)}°C</span>`
            + ` · <span style="color:${humColor(out.humidity)}">${out.humidity}%</span>`
            + aqiHtml;
    }
}

export function updateSensorsCount(sensors) {
    const active = sensors.filter(s => s.temperature !== null).length;
    document.getElementById('sensors-count').textContent = `${active}/${sensors.length}`;
}

export function updateSensorsDetail(sensors, i18n, acReal = null) {
    const el = document.getElementById('sensors-detail');
    // F0.35: AC thermostat as first entry (not part of average)
    const acEntry = (() => {
        if (!acReal || acReal.room_temp === null) return '';
        const t = acReal.room_temp.toFixed(1) + '°C';
        const tCol = tempColor(acReal.room_temp);
        return `<div class="bg-slate-800/60 rounded-xl px-3 py-2.5 border border-slate-600/40 mb-1">
            <div class="flex items-center justify-between">
                <div class="flex items-center gap-2.5">
                    <span class="w-2.5 h-2.5 rounded-full inline-block bg-slate-500"></span>
                    <span class="text-sm font-medium text-slate-400">A/C</span>
                    <span class="text-[9px] text-slate-600 uppercase tracking-wider">∅ avg</span>
                </div>
                <span class="text-xs font-semibold" style="color:${tCol}">${t}</span>
            </div>
        </div>`;
    })();

    el.innerHTML = acEntry + sensors.map((s, i) => {
        const dot = s.online
            ? `<span class="w-2.5 h-2.5 rounded-full inline-block shadow-sm" style="background:${SENSOR_COLORS[i % SENSOR_COLORS.length]}"></span>`
            : '<span class="w-2.5 h-2.5 rounded-full inline-block bg-slate-600"></span>';
        const temp     = s.temperature !== null ? s.temperature.toFixed(1) + '°C' : '--';
        const hum      = s.humidity    !== null ? s.humidity.toFixed(0) + '%'      : '--';
        const bat      = s.battery     !== null ? s.battery + '%'                  : '--';
        const tColor   = tempColor(s.temperature);
        const hColor   = humColor(s.humidity);
        const batColor = s.battery !== null && s.battery < 20 ? '#ef4444' : '#64748b';

        let lastSeenText = '--';
        if (s.timestamp != null) {
            const d = new Date(s.timestamp * 1000);
            lastSeenText = d.toLocaleDateString('es-ES', { day: '2-digit', month: '2-digit' })
                + ' ' + d.toLocaleTimeString('es-ES', { hour: '2-digit', minute: '2-digit' });
        }

        return `<div class="bg-slate-900/40 rounded-xl px-3 py-2.5 border border-slate-700/30">
            <div class="flex items-center justify-between mb-1">
                <div class="flex items-center gap-2.5">${dot}<span class="text-sm font-medium">${s.name}</span></div>
                <div class="text-right text-xs flex items-center gap-2">
                    <span class="font-semibold" style="color:${tColor}">${temp}</span>
                    <span style="color:${hColor}">${hum}</span>
                    <span style="color:${batColor}">🔋${bat}</span>
                </div>
            </div>
            <div class="text-[10px] text-slate-500 text-right">${i18n.t('modals.sensors.lastSeen')}: ${lastSeenText}</div>
        </div>`;
    }).join('');
}

export function openModal() {
    const modal = document.getElementById('modal');
    // Reset the scrollable body (not the sheet itself) to top
    const scrollBody = modal.querySelector('[style*="overflow-y:auto"]');
    if (scrollBody) scrollBody.scrollTop = 0;
    modal.classList.remove('hidden');
    requestAnimationFrame(() => modal.classList.add('modal-visible'));
}

export function closeModal() {
    const modal = document.getElementById('modal');
    modal.classList.remove('modal-visible');
    setTimeout(() => modal.classList.add('hidden'), 300);
}

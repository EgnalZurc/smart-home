"""
Portfolio Monitor — Internationalisation (es / en).
"""

import os
from typing import Any

# ─────────────────────────────────────────────────────────────────────────────
# Translation catalogue
# ─────────────────────────────────────────────────────────────────────────────
_CATALOGUE: dict[str, dict[str, str]] = {
    # ── General ───────────────────────────────────────────────────────────────
    "general.loading": {"es": "Cargando...", "en": "Loading..."},
    "general.last_update": {"es": "Última actualización", "en": "Last update"},
    "general.never": {"es": "Nunca", "en": "Never"},
    "general.error": {"es": "Error", "en": "Error"},
    # ── Alert levels ──────────────────────────────────────────────────────────
    "alert.ok": {"es": "EN ORDEN", "en": "ON TRACK"},
    "alert.info": {"es": "INFORMATIVO", "en": "INFO"},
    "alert.warn": {"es": "CORRECCIÓN", "en": "CORRECTION"},
    "alert.danger": {"es": "REVISAR", "en": "REVIEW"},
    # ── ETF monitor ───────────────────────────────────────────────────────────
    "etf.title": {"es": "📈 Monitor ETFs", "en": "📈 ETF Monitor"},
    "etf.no_funds": {"es": "No hay fondos configurados", "en": "No funds configured"},
    "etf.total_portfolio": {
        "es": "💰 Cartera Total ETFs",
        "en": "💰 Total ETF Portfolio",
    },
    "etf.phase1": {
        "es": "FASE 1 — Faltan ~{months} meses para Fase 2",
        "en": "PHASE 1 — ~{months} months until Phase 2",
    },
    "etf.phase2": {
        "es": "FASE 2 — ETFs acelerados",
        "en": "PHASE 2 — Accelerated ETFs",
    },
    "etf.current_price": {"es": "Precio actual", "en": "Current price"},
    "etf.avg_cost": {"es": "Precio medio", "en": "Average cost"},
    "etf.units": {"es": "Participaciones", "en": "Units"},
    "etf.value": {"es": "Valor actual", "en": "Current value"},
    "etf.gain_loss": {"es": "Ganancia/pérdida", "en": "Gain/loss"},
    "etf.monthly_contrib": {"es": "Aportación mensual", "en": "Monthly contribution"},
    "etf.high_52w": {"es": "Máx 52 semanas", "en": "52w high"},
    "etf.low_52w": {"es": "Mín 52 semanas", "en": "52w low"},
    "etf.ma50": {"es": "Media móvil 50d", "en": "50d MA"},
    "etf.ma200": {"es": "Media móvil 200d", "en": "200d MA"},
    "etf.drawdown": {"es": "Caída vs máx", "en": "Drop vs high"},
    "etf.volatility": {"es": "Volatilidad anual", "en": "Annual volatility"},
    "etf.chg_1d": {"es": "1 día", "en": "1 day"},
    "etf.chg_1m": {"es": "1 mes", "en": "1 month"},
    "etf.chg_3m": {"es": "3 meses", "en": "3 months"},
    "etf.chg_ytd": {"es": "Año actual", "en": "YTD"},
    "etf.signals": {"es": "Señales detectadas", "en": "Detected signals"},
    "etf.tax_title": {
        "es": "💶 Impacto fiscal si vendieras hoy",
        "en": "💶 Tax impact if sold today",
    },
    "etf.tax_gain": {"es": "Ganancia bruta", "en": "Gross gain"},
    "etf.tax_irpf": {"es": "Impuesto IRPF", "en": "IRPF tax"},
    "etf.tax_net": {"es": "Neto a bolsillo", "en": "Net cash"},
    "etf.proj_title": {
        "es": "📊 Seguimiento del plan — Año {year}",
        "en": "📊 Plan tracking — Year {year}",
    },
    "etf.proj_expected": {"es": "Valor proyectado", "en": "Projected value"},
    "etf.proj_actual": {"es": "Valor real", "en": "Actual value"},
    "etf.proj_deviation": {"es": "Desviación", "en": "Deviation"},
    # ── ETF signals ───────────────────────────────────────────────────────────
    "signal.mm200.title": {"es": "⚠️ Precio bajo MM200", "en": "⚠️ Price below MA200"},
    "signal.mm200.body": {
        "es": "Precio ({price:.2f}) bajo MM200 ({mm:.2f}) <span class=\"negative\">({pct:+.2f}%)</span>. Tendencia bajista.",
        "en": "Price ({price:.2f}) below MA200 ({mm:.2f}) <span class=\"negative\">({pct:+.2f}%)</span>. Bearish trend.",
    },
    "signal.mm50.title": {"es": "📉 Precio bajo MM50", "en": "📉 Price below MA50"},
    "signal.mm50.body": {
        "es": "Precio ({price:.2f}) bajo MM50 ({mm:.2f}) <span class=\"negative\">({pct:+.2f}%)</span>. Corrección a corto plazo.",
        "en": "Price ({price:.2f}) below MA50 ({mm:.2f}) <span class=\"negative\">({pct:+.2f}%)</span>. Short-term correction.",
    },
    "signal.mm_ok.title": {
        "es": "✅ Precio sobre ambas medias",
        "en": "✅ Price above both MAs",
    },
    "signal.mm_ok.body": {
        "es": "Precio ({price:.2f}) sobre MM50 <span class=\"positive\">({pct50:+.2f}%)</span> y MM200 <span class=\"positive\">({pct200:+.2f}%)</span>.",
        "en": "Price ({price:.2f}) above MA50 <span class=\"positive\">({pct50:+.2f}%)</span> and MA200 <span class=\"positive\">({pct200:+.2f}%)</span>.",
    },
    # NOTE: Golden/Death Cross are lagging indicators - best for trend confirmation, not entry triggers
    "signal.golden.title": {"es": "🟡 Golden Cross", "en": "🟡 Golden Cross"},
    "signal.golden.body": {
        "es": "MM50 cruzó al alza MM200. Indica posible cambio a tendencia alcista (indicador retrasado).",
        "en": "MA50 crossed above MA200. Suggests potential shift to uptrend (lagging indicator).",
    },
    "signal.death.title": {"es": "🔴 Death Cross", "en": "🔴 Death Cross"},
    "signal.death.body": {
        "es": "MM50 cruzó a la baja MM200. Indica posible cambio a tendencia bajista (indicador retrasado).",
        "en": "MA50 crossed below MA200. Suggests potential shift to downtrend (lagging indicator).",
    },
    "signal.drop_severe.title": {
        "es": "🚨 Caída severa desde máximo",
        "en": "🚨 Severe drop from high",
    },
    "signal.drop_severe.body": {
        "es": "{pct:.1%} desde máximo 52s ({high:.2f}). Revisar posición.",
        "en": "{pct:.1%} from 52w high ({high:.2f}). Review position.",
    },
    "signal.drop_warn.title": {
        "es": "⚠️ Corrección notable",
        "en": "⚠️ Notable correction",
    },
    "signal.drop_warn.body": {
        "es": "{pct:.1%} desde máximo 52s ({high:.2f}).",
        "en": "{pct:.1%} from 52w high ({high:.2f}).",
    },
    "signal.loss_crit.title": {
        "es": "🚨 PÉRDIDA REAL CRÍTICA",
        "en": "🚨 CRITICAL REAL LOSS",
    },
    "signal.loss_crit.body": {
        "es": "Perdiendo {pct:.1%} sobre precio medio ({avg:.2f}€).",
        "en": "Losing {pct:.1%} vs average cost ({avg:.2f}€).",
    },
    "signal.loss_warn.title": {
        "es": "⚠️ En pérdidas sobre coste",
        "en": "⚠️ Below average cost",
    },
    "signal.loss_warn.body": {
        "es": "{pct:.1%} bajo precio medio ({avg:.2f}€).",
        "en": "{pct:.1%} below average cost ({avg:.2f}€).",
    },
    "signal.profit.title": {"es": "✅ En beneficio", "en": "✅ In profit"},
    "signal.profit.body": {
        "es": "+{pct:.1%} sobre precio medio ({avg:.2f}€).",
        "en": "+{pct:.1%} above average cost ({avg:.2f}€).",
    },
    "signal.volatility.title": {
        "es": "📊 Alta volatilidad",
        "en": "📊 High volatility",
    },
    "signal.volatility.body": {
        "es": "Volatilidad anualizada: {vol:.1%}.",
        "en": "Annualised volatility: {vol:.1%}.",
    },
    # ── ETF recommendations ───────────────────────────────────────────────────
    # NOTE: These are informational, not financial advice
    "rec.danger.title": {
        "es": "🚨 SEÑALES CRÍTICAS DETECTADAS",
        "en": "🚨 CRITICAL SIGNALS DETECTED",
    },
    "rec.danger.body": {
        "es": "Hay señales importantes en {name}. Revisa si la tesis sigue vigente.",
        "en": "Important signals for {name}. Check if the investment thesis still holds.",
    },
    "rec.warn.title": {"es": "⚠️ CORRECCIÓN EN CURSO", "en": "⚠️ CORRECTION UNDERWAY"},
    "rec.warn.body": {
        "es": "{name} muestra corrección. Históricamente, DCA funciona bien en correcciones.",
        "en": "{name} showing correction. Historically, DCA works well during corrections.",
    },
    "rec.ok.title": {"es": "✅ TENDENCIA POSITIVA", "en": "✅ POSITIVE TREND"},
    "rec.ok.body": {
        "es": "{name} sigue tendencia positiva.",
        "en": "{name} following positive trend.",
    },
    # ── Crypto monitor ────────────────────────────────────────────────────────
    "crypto.title": {
        "es": "📊 Monitor Crypto Staking",
        "en": "📊 Crypto Staking Monitor",
    },
    "crypto.no_positions": {
        "es": "No hay posiciones configuradas",
        "en": "No positions configured",
    },
    "crypto.total_value": {
        "es": "💰 Valor Total Staking",
        "en": "💰 Total Staking Value",
    },
    "crypto.fear_greed": {"es": "Fear & Greed", "en": "Fear & Greed"},
    "crypto.amount": {"es": "Cantidad", "en": "Amount"},
    "crypto.value": {"es": "Valor actual", "en": "Current value"},
    "crypto.product": {"es": "Producto", "en": "Product"},
    "crypto.apy": {"es": "APY", "en": "APY"},
    "crypto.daily_gain": {"es": "Ganancia/día", "en": "Daily gain"},
    "crypto.accumulated": {"es": "Acumulado staking", "en": "Staking accumulated"},
    "crypto.since": {"es": "desde {date}", "en": "since {date}"},
    "crypto.available_now": {"es": "Disponible ahora", "en": "Available now"},
    "crypto.available_in": {
        "es": "Disponible en {days}d",
        "en": "Available in {days}d",
    },
    "crypto.matures": {"es": "Vence: {date}", "en": "Matures: {date}"},
    "crypto.next_reward": {
        "es": "Próxima recompensa: {days}d",
        "en": "Next reward: {days}d",
    },
    "crypto.flexible": {"es": "Flexible", "en": "Flexible"},
    "crypto.fixed": {"es": "Fijo", "en": "Fixed"},
    "crypto.chg_24h": {"es": "24h", "en": "24h"},
    "crypto.chg_30d": {"es": "30d", "en": "30d"},
    "crypto.ath_distance": {"es": "Dist. ATH", "en": "ATH dist."},
    # ── Crypto signals ────────────────────────────────────────────────────────
    # NOTE: Fear & Greed is a sentiment indicator, not a price predictor
    "crypto.fg_extreme_greed": {
        "es": "🔴 Fear & Greed en Codicia Extrema ({val}). Sentimiento de euforia — precaución.",
        "en": "🔴 Fear & Greed at Extreme Greed ({val}). Euphoric sentiment — use caution.",
    },
    "crypto.fg_high_greed": {
        "es": "🟡 Fear & Greed elevado ({val}). Sentimiento optimista elevado.",
        "en": "🟡 Fear & Greed high ({val}). Elevated bullish sentiment.",
    },
    "crypto.fg_extreme_fear": {
        "es": "🟢 Fear & Greed en Miedo Extremo ({val}). Sentimiento pesimista — posible oportunidad.",
        "en": "🟢 Fear & Greed at Extreme Fear ({val}). Pessimistic sentiment — potential opportunity.",
    },
    "crypto.drop_danger": {
        "es": "🔴 Caída de {pct:.1f}% en 24h. Vigilar si continúa.",
        "en": "🔴 Drop of {pct:.1f}% in 24h. Watch if it continues.",
    },
    "crypto.drop_warn": {
        "es": "🟡 Caída de {pct:.1f}% en 24h.",
        "en": "🟡 Drop of {pct:.1f}% in 24h.",
    },
    "crypto.pump_warn": {
        "es": "📈 Subida fuerte +{pct:.1f}% en 24h.",
        "en": "📈 Strong surge +{pct:.1f}% in 24h.",
    },
    "crypto.ath_danger": {
        "es": "📈 A solo {pct:.1f}% del ATH. Zona de máximos históricos.",
        "en": "📈 Only {pct:.1f}% from ATH. Near all-time high zone.",
    },
    "crypto.ath_warn": {
        "es": "📈 A {pct:.1f}% del ATH. Acercándose a máximos.",
        "en": "📈 {pct:.1f}% from ATH. Approaching highs.",
    },
    "crypto.bear_30d": {
        "es": "🟡 Bajada del {pct:.1f}% en 30 días. Tendencia bajista sostenida.",
        "en": "🟡 Down {pct:.1f}% in 30 days. Sustained bearish trend.",
    },
    "crypto.bull_30d": {
        "es": "🟢 Subida del +{pct:.1f}% en 30 días. Tendencia alcista fuerte.",
        "en": "🟢 Up +{pct:.1f}% in 30 days. Strong bullish trend.",
    },
    # ── Status messages ───────────────────────────────────────────────────────
    "status.danger": {
        "es": "⚠️ ACCIÓN RECOMENDADA — Revisa las alertas rojas",
        "en": "⚠️ ACTION REQUIRED — Review red alerts",
    },
    "status.warning": {
        "es": "🔔 HAY AVISOS — Revisa las alertas amarillas",
        "en": "🔔 WARNINGS — Review yellow alerts",
    },
    "status.ok": {
        "es": "✅ TODO TRANQUILO — No hay acciones urgentes hoy",
        "en": "✅ ALL CLEAR — No urgent actions today",
    },
    "status.no_alerts": {
        "es": "✅ Sin alertas para este activo",
        "en": "✅ No alerts for this asset",
    },
    # ── Dashboard ─────────────────────────────────────────────────────────────
    "dashboard.title": {"es": "📊 Monitor de Cartera", "en": "📊 Portfolio Monitor"},
    "dashboard.etf_tab": {"es": "ETFs", "en": "ETFs"},
    "dashboard.crypto_tab": {"es": "Crypto", "en": "Crypto"},
    "dashboard.refresh": {"es": "Actualizar", "en": "Refresh"},
    "dashboard.auto_refresh": {"es": "Auto-actualizar", "en": "Auto-refresh"},
    "dashboard.schedule": {"es": "Programación", "en": "Schedule"},
    "dashboard.next_etf": {"es": "Próx. ETF: {time}", "en": "Next ETF: {time}"},
    "dashboard.next_crypto": {
        "es": "Próx. Crypto: {time}",
        "en": "Next Crypto: {time}",
    },
}

# ─────────────────────────────────────────────────────────────────────────────
# Language resolution
# ─────────────────────────────────────────────────────────────────────────────
_SUPPORTED = {"es", "en"}
_DEFAULT = "es"


def _resolve_lang() -> str:
    """Resolve active language: env var > default."""
    lang = os.environ.get("MONITOR_LANG", _DEFAULT).lower()
    return lang if lang in _SUPPORTED else _DEFAULT


def t(key: str, **kwargs: Any) -> str:
    """
    Return the translated string for *key* in the active language.
    Keyword arguments are interpolated via str.format_map.
    Falls back to the key itself if not found.
    """
    lang = _resolve_lang()
    entry = _CATALOGUE.get(key, {})
    text = entry.get(lang) or entry.get(_DEFAULT) or key
    return text.format_map(kwargs) if kwargs else text

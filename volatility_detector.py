"""
Volatility Detector
Monitors ATR relative to its average.
When volatility spikes — widens TP targets automatically.
Also detects session volatility regime (low/normal/high/extreme).
"""

import logging
import numpy as np
from data_fetcher import fetch_bars, compute_atr

log = logging.getLogger('ALERT.VOLATILITY')

# Volatility regimes based on ATR vs its 20-period average
REGIMES = {
    'low':     {'atr_mult': 0.7,  'tp_mult': 1.5, 'label': '🔵 Low',     'description': 'Tight range — smaller moves expected'},
    'normal':  {'atr_mult': 1.0,  'tp_mult': 2.0, 'label': '🟢 Normal',  'description': 'Standard conditions'},
    'high':    {'atr_mult': 1.5,  'tp_mult': 2.8, 'label': '🟡 High',    'description': 'Elevated volatility — wider TP'},
    'extreme': {'atr_mult': 2.5,  'tp_mult': 4.0, 'label': '🔴 Extreme', 'description': 'Exceptional move — max TP, tight SL'},
}


class VolatilityDetector:
    def __init__(self):
        self._cache = {}   # symbol → {regime, atr, atr_avg, timestamp}

    def analyse(self, symbol: str, bars: list = None) -> dict:
        """
        Analyse current volatility for a symbol.
        Returns regime dict with TP multiplier to use.
        """
        try:
            if bars is None:
                bars = fetch_bars(symbol, '5m', 60)

            if len(bars) < 20:
                return self._default()

            # Current ATR (last 14 bars)
            current_atr = compute_atr(bars, period=14)

            # Average ATR over last 20 periods (ATR of ATRs)
            atrs = []
            for i in range(14, len(bars)):
                atrs.append(compute_atr(bars[:i], period=14))
            atr_avg = float(np.mean(atrs[-20:])) if atrs else current_atr

            if atr_avg == 0:
                return self._default()

            ratio = current_atr / atr_avg

            # Determine regime
            if ratio >= 2.5:
                regime_key = 'extreme'
            elif ratio >= 1.5:
                regime_key = 'high'
            elif ratio <= 0.7:
                regime_key = 'low'
            else:
                regime_key = 'normal'

            regime = REGIMES[regime_key].copy()
            regime.update({
                'regime':      regime_key,
                'current_atr': round(current_atr, 4),
                'atr_avg':     round(atr_avg, 4),
                'atr_ratio':   round(ratio, 2),
                'symbol':      symbol,
            })

            self._cache[symbol] = regime

            if regime_key in ('high', 'extreme'):
                log.warning(f"{symbol} volatility: {regime['label']} (ATR {ratio:.1f}x average)")
            else:
                log.info(f"{symbol} volatility: {regime['label']} (ATR {ratio:.1f}x average)")

            return regime

        except Exception as e:
            log.error(f"Volatility analysis error: {e}")
            return self._default()

    def adjust_targets(self, entry: float, stop_loss: float,
                       direction: str, regime: dict) -> dict:
        """
        Adjust TP based on volatility regime.
        SL stays the same — only TP is widened.
        Returns adjusted entry levels.
        """
        stop_dist = abs(entry - stop_loss)
        tp_mult   = regime.get('tp_mult', 2.0)

        if direction == 'bullish':
            take_profit = entry + stop_dist * tp_mult
        else:
            take_profit = entry - stop_dist * tp_mult

        rr_actual = round(tp_mult, 1)

        return {
            'take_profit':  round(take_profit, 4),
            'stop_loss':    round(stop_loss, 4),
            'rr_ratio':     rr_actual,
            'tp_multiplier': tp_mult,
            'regime':        regime['regime'],
            'regime_label':  regime['label'],
        }

    def _default(self) -> dict:
        regime = REGIMES['normal'].copy()
        regime.update({
            'regime':      'normal',
            'current_atr': 0,
            'atr_avg':     0,
            'atr_ratio':   1.0,
            'symbol':      'unknown',
        })
        return regime


def format_volatility_line(regime: dict) -> str:
    """One-line summary for Telegram alert."""
    label  = regime.get('label', '🟢 Normal')
    ratio  = regime.get('atr_ratio', 1.0)
    tp_m   = regime.get('tp_mult', 2.0)
    desc   = regime.get('description', '')

    if regime.get('regime') in ('high', 'extreme'):
        return (
            f"⚡ <b>Volatility:</b> {label} (ATR {ratio:.1f}x avg)\n"
            f"   TP widened to {tp_m}x — {desc}"
        )
    return f"📊 <b>Volatility:</b> {label} (ATR {ratio:.1f}x avg)"

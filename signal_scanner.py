"""
Signal Scanner — Institutional Grade
All 4 institutional indicators must confirm:
  1. Liquidity Sweep
  2. Order Flow Imbalance
  3. Volume Profile
  4. Anchored VWAP
Plus original scoring system (candle patterns, S/R, trend).
"""

import logging
import numpy as np
from typing import Optional
from data_fetcher import fetch_bars, get_dxy_bias, compute_atr, compute_avg_volume
from institutional_indicators import InstitutionalAnalyser, format_institutional_summary

log = logging.getLogger('ALERT.SCANNER')


def _ema(values: list, period: int) -> float:
    if len(values) < period:
        return values[-1] if values else 0.0
    k = 2 / (period + 1)
    ema = values[0]
    for v in values[1:]:
        ema = v * k + ema * (1 - k)
    return ema

def get_15m_trend(bars: list) -> str:
    if len(bars) < 21:
        return 'neutral'
    closes = [b['close'] for b in bars]
    ef = _ema(closes, 9)
    es = _ema(closes, 21)
    if ef > es * 1.0005:   return 'bullish'
    elif ef < es * 0.9995: return 'bearish'
    return 'neutral'

def find_sr_levels(bars: list, window: int = 5, tolerance: float = 0.003):
    highs = [b['high'] for b in bars]
    lows  = [b['low']  for b in bars]
    swing_highs, swing_lows = [], []
    for i in range(window, len(bars) - window):
        if highs[i] == max(highs[i-window:i+window+1]):
            swing_highs.append(highs[i])
        if lows[i] == min(lows[i-window:i+window+1]):
            swing_lows.append(lows[i])

    def cluster(levels):
        if not levels: return []
        levels = sorted(levels)
        clusters = [[levels[0]]]
        for lv in levels[1:]:
            if abs(lv - clusters[-1][-1]) / clusters[-1][-1] < tolerance:
                clusters[-1].append(lv)
            else:
                clusters.append([lv])
        return [float(np.mean(c)) for c in clusters]

    return {'resistance': cluster(swing_highs), 'support': cluster(swing_lows)}

def near_level(price: float, levels: list, threshold: float = 0.001):
    for lv in levels:
        if abs(price - lv) / lv <= threshold:
            return True, lv
    return False, 0.0

def score_candles(bars: list, level: float, level_type: str,
                  avg_vol: float, confirm_n: int) -> Optional[dict]:
    """Original candle scoring — unchanged."""
    if len(bars) < 10:
        return None

    last  = bars[-1]
    score = 0
    notes = []

    def body(b):  return abs(b['close'] - b['open'])
    def rng(b):   return max(b['high'] - b['low'], 0.0001)
    def lwick(b): return min(b['open'], b['close']) - b['low']
    def uwick(b): return b['high'] - max(b['open'], b['close'])
    def bull(b):  return b['close'] > b['open']
    def bear(b):  return b['close'] < b['open']

    r = rng(last)

    if level_type == 'support':
        direction = 'bullish'
        swept = last['low'] < level and last['close'] > level
        if swept:
            wr = lwick(last) / r
            score += 35 if wr >= 0.7 else 22 if wr >= 0.5 else 10
            notes.append('Sweep' if wr >= 0.5 else 'Weak sweep')
        elif abs(last['close'] - level) / level < 0.0005:
            score += 10
            notes.append('Near support')

        is_hammer    = lwick(last) >= r * 0.55 and body(last) <= r * 0.35
        is_engulf    = (len(bars) >= 2 and bear(bars[-2]) and bull(last)
                        and last['open'] <= bars[-2]['close']
                        and last['close'] >= bars[-2]['open'])
        is_bull_close = bull(last) and body(last) >= r * 0.5

        if is_hammer and is_engulf:   score += 35; notes.append('Hammer+Engulf')
        elif is_hammer:               score += 30; notes.append('Hammer')
        elif is_engulf:               score += 28; notes.append('Bull engulfing')
        elif is_bull_close:           score += 15; notes.append('Bull close')

        bull_count = sum(1 for b in bars[-confirm_n:] if bull(b))
        score += int((bull_count / confirm_n) * 20)
        notes.append(f'{bull_count}/{confirm_n} bull')

    elif level_type == 'resistance':
        direction = 'bearish'
        swept = last['high'] > level and last['close'] < level
        if swept:
            wr = uwick(last) / r
            score += 35 if wr >= 0.7 else 22 if wr >= 0.5 else 10
            notes.append('Sweep' if wr >= 0.5 else 'Weak sweep')
        elif abs(last['close'] - level) / level < 0.0005:
            score += 10
            notes.append('Near resistance')

        is_star   = uwick(last) >= r * 0.55 and body(last) <= r * 0.35
        is_engulf = (len(bars) >= 2 and bull(bars[-2]) and bear(last)
                     and last['open'] >= bars[-2]['close']
                     and last['close'] <= bars[-2]['open'])
        is_bear_close = bear(last) and body(last) >= r * 0.5

        if is_star and is_engulf:     score += 35; notes.append('Star+Engulf')
        elif is_star:                 score += 30; notes.append('Shooting star')
        elif is_engulf:               score += 28; notes.append('Bear engulfing')
        elif is_bear_close:           score += 15; notes.append('Bear close')

        bear_count = sum(1 for b in bars[-confirm_n:] if bear(b))
        score += int((bear_count / confirm_n) * 20)
        notes.append(f'{bear_count}/{confirm_n} bear')

    else:
        return None

    # Volume — soft scoring only
    vol_ratio = 0.0
    if avg_vol > 0 and last['volume'] > 0:
        vol_ratio = last['volume'] / avg_vol
        if vol_ratio >= 1.5:   score += 10; notes.append(f'Vol {vol_ratio:.1f}x')
        elif vol_ratio >= 1.0: score += 5;  notes.append(f'Vol {vol_ratio:.1f}x')
        else:                  notes.append(f'Vol {vol_ratio:.1f}x (thin)')
    else:
        score += 3

    if score < 45:  # hard minimum — per-symbol min_score checked in scanner
        log.debug(f"Candle score too low: {score}/100")
        return None

    quality = '⭐⭐⭐ STRONG' if score >= 85 else '⭐⭐ GOOD' if score >= 72 else '⭐ MODERATE'

    return {
        'direction':    direction,
        'score':        score,
        'quality':      quality,
        'notes':        notes,
        'volume_ratio': round(vol_ratio, 2),
    }


class SignalScanner:
    def __init__(self, config: dict):
        self.cfg  = config
        self.s    = config['strategy']
        self.r    = config['risk']
        self.inst = InstitutionalAnalyser()

    def scan(self) -> list:
        signals = []
        dxy = get_dxy_bias()
        log.info(f"DXY bias: {dxy}")

        gold_sig   = self._check_symbol('XAUUSD', dxy)
        silver_sig = self._check_symbol('XAGUSD', dxy)

        # Correlation check — both signalling same direction = stronger confirmation
        correlated = (
            gold_sig and silver_sig and
            gold_sig['direction'] == silver_sig['direction']
        )

        if correlated:
            direction = gold_sig['direction']
            log.info(f"CORRELATION: Gold + Silver both {direction} — boosting tier")
            for sig in [gold_sig, silver_sig]:
                sig['correlated']       = True
                sig['correlation_note'] = f"Gold & Silver both {direction.upper()} simultaneously"
                # Upgrade tier if correlated
                if '⭐⭐' not in sig.get('signal_tier',''):
                    sig['signal_tier'] = '⭐⭐ STANDARD'
                    sig['tier_note']   = sig['tier_note'] + ' + XAU/XAG correlation'
                elif '⭐⭐⭐' not in sig.get('signal_tier',''):
                    sig['signal_tier'] = '⭐⭐⭐ STRONG'
                    sig['tier_note']   = sig['tier_note'] + ' + XAU/XAG correlation'
        else:
            if gold_sig:   gold_sig['correlated']   = False
            if silver_sig: silver_sig['correlated'] = False

        if gold_sig:   signals.append(gold_sig)
        if silver_sig: signals.append(silver_sig)
        return signals

    def _check_symbol(self, symbol: str, dxy: str) -> Optional[dict]:
        is_gold   = 'XAU' in symbol
        confirm_n = (self.s['gold_confirmation_candles'] if is_gold
                     else self.s['silver_confirmation_candles'])

        # Per-symbol parameter overrides
        sym_cfg       = self.s.get(symbol, {})
        sr_threshold  = sym_cfg.get('sr_touch_threshold',  self.s['sr_touch_threshold'])
        atr_mult      = sym_cfg.get('atr_stop_multiplier', self.r['atr_stop_multiplier'])
        rr_ratio      = sym_cfg.get('rr_ratio',            self.r['rr_ratio'])
        min_score     = sym_cfg.get('min_score',           45)
        inst_required = sym_cfg.get('inst_required', 1)

        # Fetch multiple timeframes
        # 3m = signal candles (faster, more signals)
        # 5m = candle scoring + volume
        # 15m = S/R levels + trend context (higher timeframe structure)
        bars_3m  = fetch_bars(symbol, '3m',  120)
        bars_5m  = fetch_bars(symbol, '5m',  80)
        bars_15m = fetch_bars(symbol, '15m', 60)
        bars_1m  = fetch_bars(symbol, '1m',  30)

        # Use 3m if available, fall back to 5m
        bars_signal = bars_3m if len(bars_3m) >= 30 else bars_5m

        if len(bars_signal) < 20 or len(bars_15m) < 20:
            log.warning(f"Insufficient data: {symbol}")
            return None

        price = bars_signal[-1]['close']

        # S/R levels — always from 15m for structure
        sr       = find_sr_levels(bars_15m, tolerance=sr_threshold * 3)
        near_sup, s_lv = near_level(price, sr['support'],    sr_threshold)
        near_res, r_lv = near_level(price, sr['resistance'], sr_threshold)

        if not near_sup and not near_res:
            log.debug(f"{symbol}: Not near S/R")
            return None

        level      = s_lv if near_sup else r_lv
        level_type = 'support' if near_sup else 'resistance'
        req_trend  = 'bullish' if near_sup else 'bearish'
        trend_15m  = get_15m_trend(bars_15m)

        # Trend filter: counter-trend needs higher score threshold
        if trend_15m not in (req_trend, 'neutral'):
            counter_trend = True
            log.debug(f"{symbol}: counter-trend signal ({trend_15m} vs {req_trend}) — needs score 70+")
        else:
            counter_trend = False

        avg_vol = compute_avg_volume(bars_signal, self.s['volume_lookback'])
        atr     = compute_atr(bars_signal)

        # ── STEP 1: Candle pattern scoring ────────────────────────────────────
        candle_result = score_candles(bars_signal, level, level_type, avg_vol, confirm_n)
        if not candle_result:
            return None

        direction = candle_result['direction']

        # ── STEP 2: Institutional indicators (ALL 4 must confirm) ─────────────
        inst_result = self.inst.analyse(
            bars_5m    = bars_signal,  # 3m or 5m
            bars_1m    = bars_1m,
            level      = level,
            level_type = level_type,
            direction  = direction,
            avg_vol    = avg_vol,
        )

        confirmed_count = inst_result['confirmed_count']
        log.info(
            f"{symbol} {direction}: candle={candle_result['score']}/100 "
            f"institutional={confirmed_count}/4 "
            f"({'PASS' if inst_result['all_confirmed'] else 'FAIL'})"
        )

        # TIERED: per-symbol minimum to fire, label reflects quality
        if confirmed_count < inst_required:
            log.info(
                f"{symbol}: Blocked — only {confirmed_count}/4 institutional "
                f"indicators confirmed. Need at least 2."
            )
            return None

        # Dynamic score threshold based on trend alignment
        candle_score = candle_result['score']
        if counter_trend:
            effective_min = 70  # counter-trend needs strong confirmation
        elif trend_15m == 'neutral':
            effective_min = 55  # neutral trend needs moderate confirmation
        else:
            effective_min = min_score  # trend agrees — standard threshold (45)

        if candle_score < effective_min:
            log.info(f"{symbol}: Score {candle_score} below threshold {effective_min} (trend={trend_15m})")
            return None

        # Signal tier based on confirmation count + candle score
        if inst_result['all_confirmed'] and candle_score >= 72:
            signal_tier  = '⭐⭐⭐ STRONG'
            tier_note    = '4/4 institutional + high score'
        elif confirmed_count >= 3 and candle_score >= 60:
            signal_tier  = '⭐⭐ STANDARD'
            tier_note    = f'{confirmed_count}/4 institutional confirmed'
        else:
            signal_tier  = '⭐ RELAXED'
            tier_note    = f'{confirmed_count}/4 institutional — lower confidence'

        # Pass tier into signal
        candle_result['signal_tier'] = signal_tier
        candle_result['tier_note']   = tier_note

        # ── STEP 3: Build order (uses per-symbol atr_mult and rr_ratio) ──────
        stop_dist   = atr * atr_mult
        stop_loss   = (price - stop_dist if direction == 'bullish'
                       else price + stop_dist)
        take_profit = (price + stop_dist * rr_ratio if direction == 'bullish'
                       else price - stop_dist * rr_ratio)

        capital    = self.r['starting_capital']
        risk_eur   = capital * self.r['risk_per_trade_pct']
        etoro_units = round(risk_eur / stop_dist, 2) if stop_dist > 0 else 0.01

        # ── STEP 4: Combine quality labels ───────────────────────────────────
        combined_notes = candle_result['notes'] + inst_result['sweep'].get('description','').split(' | ')

        return {
            'symbol':          symbol,
            'is_silver':       not is_gold,
            'direction':       direction,
            'entry_price':     round(price, 4),
            'level':           round(level, 4),
            'level_type':      level_type,
            'trend_15m':       trend_15m,  # 15m structure trend
            'dxy_bias':        dxy,
            'volume_ratio':    candle_result['volume_ratio'],
            'signal_score':    candle_result['score'],
            'signal_quality':  candle_result['quality'],
            'signal_notes':    candle_result['notes'],
            'inst_result':     inst_result,
            'inst_summary':    format_institutional_summary(inst_result),
            'session_vwap':    inst_result['session_vwap'],
            'daily_vwap':      inst_result['daily_vwap'],
            'poc':             inst_result['poc'],
            'va_high':         inst_result['va_high'],
            'va_low':          inst_result['va_low'],
            'atr':             round(atr, 4),
            'order': {
                'stop_loss':   round(stop_loss, 4),
                'take_profit': round(take_profit, 4),
                'rr_ratio':    self.r['rr_ratio'],
                'risk_eur':    round(risk_eur, 2),
                'risk_pct':    self.r['risk_per_trade_pct'] * 100,
                'etoro_units': etoro_units,
            }
        }

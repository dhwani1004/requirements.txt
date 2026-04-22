"""
Institutional Indicators
Approximations using OHLCV bar data.

1. Enhanced Liquidity Sweep    — detects stop hunts above/below key levels
2. Order Flow Imbalance        — approximates buying/selling pressure per bar
3. Volume Profile              — finds high volume nodes (HVN) and low volume nodes (LVN)
4. Anchored VWAP               — VWAP anchored from session open or key swing point

All four must confirm signal direction for alert to fire.
"""

import logging
import numpy as np
from datetime import datetime, timezone, time as dtime

log = logging.getLogger('ALERT.INDICATORS')


# ══════════════════════════════════════════════════════════════════════════════
# 1. ENHANCED LIQUIDITY SWEEP
# ══════════════════════════════════════════════════════════════════════════════

class LiquiditySweep:
    """
    Detects institutional stop hunts.
    A sweep occurs when price wicks beyond a key level (taking out stops)
    then immediately reverses — showing smart money absorbed the liquidity.

    Grades:
      STRONG  — deep wick beyond level, fast reversal, high volume on reversal
      MODERATE — wick beyond level, closes back inside
      WEAK    — just touches level, minimal wick
    """

    def analyse(self, bars: list, level: float, level_type: str,
                avg_vol: float) -> dict:
        if len(bars) < 5:
            return self._none()

        last  = bars[-1]
        prev  = bars[-2] if len(bars) >= 2 else last
        candle_range = max(last['high'] - last['low'], 0.0001)

        def lwick(b): return min(b['open'], b['close']) - b['low']
        def uwick(b): return b['high'] - max(b['open'], b['close'])
        def bull(b):  return b['close'] > b['open']
        def bear(b):  return b['close'] < b['open']

        if level_type == 'support':
            # Price swept below support then closed back above
            swept        = last['low'] < level and last['close'] > level
            wick_size    = lwick(last)
            sweep_depth  = max(level - last['low'], 0)
            reversal_str = last['close'] - last['open'] if bull(last) else 0
            closes_above = last['close'] > level

            if not swept:
                return self._none()

            wick_ratio = wick_size / candle_range
            vol_spike  = last['volume'] >= avg_vol * 1.2 if avg_vol > 0 else False

            if wick_ratio >= 0.65 and vol_spike and bull(last):
                grade = 'STRONG'
                score = 35
            elif wick_ratio >= 0.50 and closes_above:
                grade = 'MODERATE'
                score = 22
            else:
                grade = 'WEAK'
                score = 10

            return {
                'detected':    True,
                'direction':   'bullish',
                'grade':       grade,
                'score':       score,
                'wick_ratio':  round(wick_ratio, 2),
                'sweep_depth': round(sweep_depth, 4),
                'description': f'{grade} bullish sweep — {round(wick_ratio*100)}% wick below support',
            }

        elif level_type == 'resistance':
            swept       = last['high'] > level and last['close'] < level
            wick_size   = uwick(last)
            sweep_depth = max(last['high'] - level, 0)
            closes_below = last['close'] < level

            if not swept:
                return self._none()

            wick_ratio = wick_size / candle_range
            vol_spike  = last['volume'] >= avg_vol * 1.2 if avg_vol > 0 else False

            if wick_ratio >= 0.65 and vol_spike and bear(last):
                grade = 'STRONG'
                score = 35
            elif wick_ratio >= 0.50 and closes_below:
                grade = 'MODERATE'
                score = 22
            else:
                grade = 'WEAK'
                score = 10

            return {
                'detected':    True,
                'direction':   'bearish',
                'grade':       grade,
                'score':       score,
                'wick_ratio':  round(wick_ratio, 2),
                'sweep_depth': round(sweep_depth, 4),
                'description': f'{grade} bearish sweep — {round(wick_ratio*100)}% wick above resistance',
            }

        return self._none()

    def _none(self):
        return {'detected': False, 'grade': 'NONE', 'score': 0, 'description': 'No sweep'}


# ══════════════════════════════════════════════════════════════════════════════
# 2. ORDER FLOW IMBALANCE
# ══════════════════════════════════════════════════════════════════════════════

class OrderFlowAnalyser:
    """
    Approximates order flow using OHLCV bars.

    Without tick data we use the CVD (Cumulative Volume Delta) approximation:
      - Bullish bar:  estimated buy volume = close_position_in_range * volume
      - Bearish bar:  estimated sell volume = (1 - close_position) * volume

    Close position = (close - low) / (high - low)
    This is the standard approximation used by many retail algo traders.

    Also detects:
    - Delta divergence (price making new high but delta not confirming)
    - Absorption (high volume bar with small body = big players absorbing)
    - Imbalance stacks (3+ consecutive bars of same direction)
    """

    def analyse(self, bars: list, direction: str) -> dict:
        if len(bars) < 10:
            return self._neutral()

        # Calculate delta for each bar
        deltas = []
        for b in bars:
            rng = max(b['high'] - b['low'], 0.0001)
            close_pos = (b['close'] - b['low']) / rng   # 0=bottom, 1=top
            buy_vol   = b['volume'] * close_pos
            sell_vol  = b['volume'] * (1 - close_pos)
            delta     = buy_vol - sell_vol
            deltas.append(delta)

        # Recent delta (last 5 bars)
        recent_delta    = sum(deltas[-5:])
        cumulative_delta = sum(deltas[-20:])

        # Imbalance stacks — consecutive same-direction bars
        stack_count = 0
        stack_dir   = 'bull' if bars[-1]['close'] > bars[-1]['open'] else 'bear'
        for b in reversed(bars[-6:]):
            if b['close'] > b['open'] and stack_dir == 'bull':
                stack_count += 1
            elif b['close'] < b['open'] and stack_dir == 'bear':
                stack_count += 1
            else:
                break

        # Absorption detection — large volume, tiny body
        last = bars[-1]
        body = abs(last['close'] - last['open'])
        rng  = max(last['high'] - last['low'], 0.0001)
        avg_vol = np.mean([b['volume'] for b in bars[-20:]]) if len(bars) >= 20 else 1
        absorption = (last['volume'] > avg_vol * 1.5 and body / rng < 0.25)

        # Delta divergence — price higher but delta lower (bearish div) or vice versa
        price_higher = bars[-1]['close'] > bars[-5]['close']
        delta_higher = deltas[-1] > deltas[-5]
        bull_div = not price_higher and delta_higher    # hidden bull div
        bear_div = price_higher and not delta_higher    # hidden bear div

        # Score for required direction
        score = 0
        notes = []

        if direction == 'bullish':
            if recent_delta > 0:
                score += 15
                notes.append(f'Delta +{recent_delta:.0f} (buying pressure)')
            if cumulative_delta > 0:
                score += 10
                notes.append('Cumulative delta bullish')
            if stack_dir == 'bull' and stack_count >= 3:
                score += 10
                notes.append(f'{stack_count} bull bars stacked')
            if absorption and last['close'] > last['open']:
                score += 10
                notes.append('Bullish absorption')
            if bull_div:
                score += 5
                notes.append('Hidden bullish divergence')

            confirmed = score >= 20
            if not confirmed:
                notes.append('Order flow weak for BUY')

        else:  # bearish
            if recent_delta < 0:
                score += 15
                notes.append(f'Delta {recent_delta:.0f} (selling pressure)')
            if cumulative_delta < 0:
                score += 10
                notes.append('Cumulative delta bearish')
            if stack_dir == 'bear' and stack_count >= 3:
                score += 10
                notes.append(f'{stack_count} bear bars stacked')
            if absorption and last['close'] < last['open']:
                score += 10
                notes.append('Bearish absorption')
            if bear_div:
                score += 5
                notes.append('Hidden bearish divergence')

            confirmed = score >= 20
            if not confirmed:
                notes.append('Order flow weak for SELL')

        return {
            'confirmed':       confirmed,
            'score':           score,
            'recent_delta':    round(recent_delta, 0),
            'cumulative_delta': round(cumulative_delta, 0),
            'stack_count':     stack_count,
            'stack_dir':       stack_dir,
            'absorption':      absorption,
            'notes':           notes,
            'description':     ' | '.join(notes[:2]),
        }

    def _neutral(self):
        return {
            'confirmed': False, 'score': 0,
            'recent_delta': 0, 'cumulative_delta': 0,
            'description': 'Insufficient data',
        }


# ══════════════════════════════════════════════════════════════════════════════
# 3. VOLUME PROFILE
# ══════════════════════════════════════════════════════════════════════════════

class VolumeProfile:
    """
    Builds a volume-at-price distribution from OHLCV bars.
    Approximates where volume traded by distributing each bar's volume
    across its price range proportionally.

    Identifies:
    - HVN (High Volume Node) — price magnet, strong S/R
    - LVN (Low Volume Node) — price moves quickly through here
    - POC (Point of Control) — single price with most volume
    - Value Area — 70% of all volume traded here

    For signal confirmation:
    - BUY near HVN support or at bottom of value area = confirmed
    - SELL near HVN resistance or at top of value area = confirmed
    - Trading through LVN = fast move expected
    """

    def __init__(self, num_bins: int = 24):
        self.num_bins = num_bins

    def build(self, bars: list) -> dict:
        if len(bars) < 20:
            return self._empty()

        prices = [b['close'] for b in bars]
        all_highs = [b['high'] for b in bars]
        all_lows  = [b['low']  for b in bars]

        price_min = min(all_lows)
        price_max = max(all_highs)
        price_range = price_max - price_min

        if price_range < 0.0001:
            return self._empty()

        bin_size = price_range / self.num_bins
        bins     = np.zeros(self.num_bins)
        bin_prices = [price_min + i * bin_size for i in range(self.num_bins)]

        # Distribute volume across price range of each bar
        for b in bars:
            bar_range = max(b['high'] - b['low'], bin_size * 0.1)
            for i, bp in enumerate(bin_prices):
                bin_top = bp + bin_size
                # How much of this bar overlaps with this bin
                overlap = max(0, min(b['high'], bin_top) - max(b['low'], bp))
                bins[i] += b['volume'] * (overlap / bar_range)

        total_vol  = bins.sum()
        poc_idx    = int(np.argmax(bins))
        poc_price  = bin_prices[poc_idx]

        # Value area — 70% of volume around POC
        va_vol_target = total_vol * 0.70
        va_vol = bins[poc_idx]
        va_low_idx  = poc_idx
        va_high_idx = poc_idx

        while va_vol < va_vol_target:
            expand_up   = va_high_idx + 1 < self.num_bins
            expand_down = va_low_idx - 1 >= 0
            if expand_up and (not expand_down or
                              bins[va_high_idx+1] >= bins[va_low_idx-1]):
                va_high_idx += 1
                va_vol += bins[va_high_idx]
            elif expand_down:
                va_low_idx -= 1
                va_vol += bins[va_low_idx]
            else:
                break

        va_high = bin_prices[va_high_idx] + bin_size
        va_low  = bin_prices[va_low_idx]

        # Find HVN and LVN
        avg_bin_vol = total_vol / self.num_bins
        hvn_prices = [bin_prices[i] for i in range(self.num_bins)
                      if bins[i] > avg_bin_vol * 1.5]
        lvn_prices = [bin_prices[i] for i in range(self.num_bins)
                      if bins[i] < avg_bin_vol * 0.5]

        return {
            'poc':        round(poc_price, 4),
            'va_high':    round(va_high, 4),
            'va_low':     round(va_low, 4),
            'hvn_prices': [round(p, 4) for p in hvn_prices],
            'lvn_prices': [round(p, 4) for p in lvn_prices],
            'bins':       bins.tolist(),
            'bin_prices': [round(p, 4) for p in bin_prices],
            'price_min':  round(price_min, 4),
            'price_max':  round(price_max, 4),
        }

    def confirm_signal(self, profile: dict, price: float,
                       direction: str, tolerance_pct: float = 0.002) -> dict:
        """Check if price is at a volume profile confirmation zone."""
        if not profile or not profile.get('poc'):
            return {'confirmed': False, 'reason': 'No profile data', 'score': 0}

        poc     = profile['poc']
        va_high = profile['va_high']
        va_low  = profile['va_low']
        tol     = price * tolerance_pct
        score   = 0
        reasons = []

        if direction == 'bullish':
            # Best: near POC or at VA Low (bottom of value area) or near HVN support
            if abs(price - va_low) <= tol:
                score += 25
                reasons.append(f'At VA Low {va_low:.2f} (value area support)')
            elif abs(price - poc) <= tol:
                score += 20
                reasons.append(f'At POC {poc:.2f} (highest volume level)')
            elif price < va_low:
                score += 15
                reasons.append('Below value area — discount zone')

            # Near HVN
            for hvn in profile.get('hvn_prices', []):
                if abs(price - hvn) <= tol * 2:
                    score += 10
                    reasons.append(f'Near HVN {hvn:.2f}')
                    break

            # In LVN — fast move down possible, risky for BUY
            for lvn in profile.get('lvn_prices', []):
                if abs(price - lvn) <= tol:
                    score -= 10
                    reasons.append(f'In LVN {lvn:.2f} — thin area')
                    break

        else:  # bearish
            if abs(price - va_high) <= tol:
                score += 25
                reasons.append(f'At VA High {va_high:.2f} (value area resistance)')
            elif abs(price - poc) <= tol:
                score += 20
                reasons.append(f'At POC {poc:.2f}')
            elif price > va_high:
                score += 15
                reasons.append('Above value area — premium zone')

            for hvn in profile.get('hvn_prices', []):
                if abs(price - hvn) <= tol * 2:
                    score += 10
                    reasons.append(f'Near HVN {hvn:.2f}')
                    break

            for lvn in profile.get('lvn_prices', []):
                if abs(price - lvn) <= tol:
                    score -= 10
                    reasons.append(f'In LVN {lvn:.2f} — thin area')
                    break

        confirmed = score >= 15
        return {
            'confirmed':  confirmed,
            'score':      score,
            'poc':        poc,
            'va_high':    va_high,
            'va_low':     va_low,
            'reasons':    reasons,
            'description': ' | '.join(reasons[:2]) if reasons else 'Not at key VP level',
        }

    def _empty(self):
        return {'poc': 0, 'va_high': 0, 'va_low': 0,
                'hvn_prices': [], 'lvn_prices': []}


# ══════════════════════════════════════════════════════════════════════════════
# 4. ANCHORED VWAP
# ══════════════════════════════════════════════════════════════════════════════

class AnchoredVWAP:
    """
    VWAP anchored from a specific point (session open, swing high/low, or key event).

    Standard VWAP = cumulative(typical_price * volume) / cumulative(volume)
    Typical price = (high + low + close) / 3

    Anchored VWAP tells you the average price all participants paid
    since a key reference point. Price above = buyers in profit.
    Price below = buyers underwater.

    For signals:
    - BUY confirmed if: price above session VWAP AND above daily VWAP
    - SELL confirmed if: price below session VWAP AND below daily VWAP
    - Extra strong: price bouncing off VWAP line as support/resistance
    """

    def calculate(self, bars: list, anchor_idx: int = 0) -> dict:
        """
        Calculate VWAP from anchor_idx bar onwards.
        anchor_idx=0 means anchor from first bar (daily)
        anchor_idx=-N means anchor from N bars ago (session)
        """
        if len(bars) < 3:
            return self._empty()

        anchored_bars = bars[anchor_idx:] if anchor_idx >= 0 else bars[anchor_idx:]

        cum_vol   = 0.0
        cum_tp_vol = 0.0
        vwap_values = []

        for b in anchored_bars:
            tp  = (b['high'] + b['low'] + b['close']) / 3
            vol = max(b['volume'], 0.0001)
            cum_vol    += vol
            cum_tp_vol += tp * vol
            vwap_values.append(cum_tp_vol / cum_vol)

        current_vwap = vwap_values[-1] if vwap_values else 0

        # Standard deviation bands (±1 and ±2 sigma)
        if len(vwap_values) >= 5:
            prices    = [(b['high'] + b['low'] + b['close']) / 3
                         for b in anchored_bars]
            deviations = [abs(p - v) for p, v in zip(prices, vwap_values)]
            std_dev    = float(np.std(deviations))
        else:
            std_dev = 0

        return {
            'vwap':        round(current_vwap, 4),
            'upper_1':     round(current_vwap + std_dev, 4),
            'lower_1':     round(current_vwap - std_dev, 4),
            'upper_2':     round(current_vwap + std_dev * 2, 4),
            'lower_2':     round(current_vwap - std_dev * 2, 4),
            'std_dev':     round(std_dev, 4),
            'vwap_values': [round(v, 4) for v in vwap_values[-10:]],
            'anchor_bars': len(anchored_bars),
        }

    def confirm_signal(self, session_vwap: dict, daily_vwap: dict,
                       price: float, direction: str) -> dict:
        """Confirm signal direction relative to VWAP levels."""
        if not session_vwap.get('vwap') or not daily_vwap.get('vwap'):
            return {'confirmed': False, 'score': 0, 'description': 'No VWAP data'}

        sv   = session_vwap['vwap']
        dv   = daily_vwap['vwap']
        sl1  = session_vwap['lower_1']
        su1  = session_vwap['upper_1']
        score = 0
        notes = []

        if direction == 'bullish':
            if price > sv:
                score += 15
                notes.append(f'Above session VWAP {sv:.2f}')
            if price > dv:
                score += 15
                notes.append(f'Above daily VWAP {dv:.2f}')

            # Bouncing off VWAP as support
            proximity = abs(price - sv) / sv
            if proximity < 0.001 and price >= sv:
                score += 15
                notes.append(f'Bouncing off VWAP {sv:.2f}')

            # At lower band — mean reversion opportunity
            if abs(price - sl1) / max(sl1, 0.001) < 0.001:
                score += 10
                notes.append(f'At -1σ band {sl1:.2f}')

            # Below both VWAPs — counter-trend, risky
            if price < sv and price < dv:
                score -= 15
                notes.append('Below both VWAPs — counter-trend BUY')

        else:  # bearish
            if price < sv:
                score += 15
                notes.append(f'Below session VWAP {sv:.2f}')
            if price < dv:
                score += 15
                notes.append(f'Below daily VWAP {dv:.2f}')

            proximity = abs(price - sv) / sv
            if proximity < 0.001 and price <= sv:
                score += 15
                notes.append(f'Rejected at VWAP {sv:.2f}')

            if abs(price - su1) / max(su1, 0.001) < 0.001:
                score += 10
                notes.append(f'At +1σ band {su1:.2f}')

            if price > sv and price > dv:
                score -= 15
                notes.append('Above both VWAPs — counter-trend SELL')

        confirmed = score >= 15
        return {
            'confirmed':      confirmed,
            'score':          score,
            'session_vwap':   sv,
            'daily_vwap':     dv,
            'notes':          notes,
            'description':    ' | '.join(notes[:2]) if notes else 'No VWAP confirmation',
        }

    def _empty(self):
        return {'vwap': 0, 'upper_1': 0, 'lower_1': 0,
                'upper_2': 0, 'lower_2': 0, 'std_dev': 0}


# ══════════════════════════════════════════════════════════════════════════════
# COMBINED INSTITUTIONAL ANALYSIS
# ══════════════════════════════════════════════════════════════════════════════

class InstitutionalAnalyser:
    """
    Runs all 4 indicators and returns a combined confirmation result.
    ALL indicators must confirm for signal to pass.
    """

    def __init__(self):
        self.sweep   = LiquiditySweep()
        self.flow    = OrderFlowAnalyser()
        self.profile = VolumeProfile()
        self.vwap    = AnchoredVWAP()

    def analyse(self, bars_5m: list, bars_1m: list,
                level: float, level_type: str,
                direction: str, avg_vol: float) -> dict:
        """
        Run all indicators. Returns combined result.
        All 4 must confirm for signal to pass (strict mode).
        """
        price = bars_5m[-1]['close'] if bars_5m else 0

        # 1. Liquidity Sweep
        sweep_result = self.sweep.analyse(bars_5m, level, level_type, avg_vol)

        # 2. Order Flow (use 1m bars for better resolution, fall back to 5m)
        flow_bars    = bars_1m if len(bars_1m) >= 10 else bars_5m
        flow_result  = self.flow.analyse(flow_bars, direction)

        # 3. Volume Profile
        vp_data      = self.profile.build(bars_5m)
        vp_result    = self.profile.confirm_signal(vp_data, price, direction)

        # 4. Anchored VWAP
        # Session VWAP: anchor from last 48 bars (~4 hours on 5m)
        # Daily VWAP: anchor from all available bars
        session_vwap = self.vwap.calculate(bars_5m, anchor_idx=max(0, len(bars_5m)-48))
        daily_vwap   = self.vwap.calculate(bars_5m, anchor_idx=0)
        vwap_result  = self.vwap.confirm_signal(session_vwap, daily_vwap, price, direction)

        # Combined score
        total_score = (
            sweep_result.get('score', 0) +
            flow_result.get('score', 0) +
            vp_result.get('score', 0) +
            vwap_result.get('score', 0)
        )

        # ALL FOUR must confirm (strict mode)
        all_confirmed = (
            sweep_result.get('detected', False) and
            flow_result.get('confirmed', False) and
            vp_result.get('confirmed', False) and
            vwap_result.get('confirmed', False)
        )

        # Count how many confirmed
        confirmed_count = sum([
            sweep_result.get('detected', False),
            flow_result.get('confirmed', False),
            vp_result.get('confirmed', False),
            vwap_result.get('confirmed', False),
        ])

        return {
            'all_confirmed':   all_confirmed,
            'confirmed_count': confirmed_count,
            'total_score':     total_score,
            'sweep':           sweep_result,
            'order_flow':      flow_result,
            'volume_profile':  vp_result,
            'vwap':            vwap_result,
            'session_vwap':    session_vwap.get('vwap', 0),
            'daily_vwap':      daily_vwap.get('vwap', 0),
            'poc':             vp_data.get('poc', 0),
            'va_high':         vp_data.get('va_high', 0),
            'va_low':          vp_data.get('va_low', 0),
        }


def format_institutional_summary(result: dict) -> str:
    """Format for Telegram alert — compact but complete."""
    sweep = result['sweep']
    flow  = result['order_flow']
    vp    = result['volume_profile']
    vwap  = result['vwap']

    def tick(confirmed): return '✅' if confirmed else '❌'

    return (
        f"🏛 <b>Institutional Confirmation ({result['confirmed_count']}/4):</b>\n"
        f"  {tick(sweep.get('detected'))} Sweep: {sweep.get('description','—')}\n"
        f"  {tick(flow.get('confirmed'))} Order Flow: {flow.get('description','—')}\n"
        f"  {tick(vp.get('confirmed'))} Vol Profile: {vp.get('description','—')}\n"
        f"  {tick(vwap.get('confirmed'))} VWAP: {vwap.get('description','—')}"
    )

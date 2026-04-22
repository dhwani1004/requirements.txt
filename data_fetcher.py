"""
Free Data Fetcher
Uses yfinance — no broker, no API key, completely free.
Gold: GC=F | Silver: SI=F | DXY: DX-Y.NYB
"""

import logging
import numpy as np

log = logging.getLogger('ALERT.DATA')

try:
    import yfinance as yf
except ImportError:
    raise ImportError("Run: pip install yfinance")


SYMBOL_MAP = {
    'XAUUSD': 'GC=F',
    'XAGUSD': 'SI=F',
    'DXY':    'DX-Y.NYB',
}

INTERVAL_MAP = {
    '5m':  '5m',
    '15m': '15m',
    '1h':  '1h',
}

PERIOD_MAP = {
    '5m':  '5d',
    '15m': '5d',
    '1h':  '30d',
}


def _v(val):
    """Safe scalar extractor — handles yfinance 1.2.0 returning Series instead of scalars."""
    if hasattr(val, 'iloc'):   return float(val.iloc[0])
    if hasattr(val, 'values'): return float(val.values[0])
    if val is None or val != val: return 0.0  # NaN check
    return float(val)


def fetch_bars(symbol: str, timeframe: str, bars: int = 120) -> list:
    """
    Fetch OHLCV bars using yfinance.
    Returns list of {time, open, high, low, close, volume}
    Compatible with yfinance 1.2.0+ which returns Series instead of scalars.
    """
    ticker   = SYMBOL_MAP.get(symbol, symbol)
    interval = INTERVAL_MAP.get(timeframe, '5m')
    period   = PERIOD_MAP.get(timeframe, '5d')

    try:
        df = yf.download(
            ticker,
            period=period,
            interval=interval,
            progress=False,
            auto_adjust=True,
            multi_level_index=False,   # yfinance 1.2.0 fix — flatten columns
        )

        if df.empty:
            log.warning(f"No data for {symbol} ({ticker})")
            return []

        # Flatten multi-level columns if present (yfinance 1.2.0 sometimes adds ticker level)
        if hasattr(df.columns, 'levels'):
            df.columns = df.columns.get_level_values(0)

        # Normalise column names — yfinance 1.2.0 may use lowercase
        df.columns = [c.capitalize() for c in df.columns]

        df = df.tail(bars)
        result = []
        for ts, row in df.iterrows():
            try:
                result.append({
                    'time':   str(ts),
                    'open':   _v(row.get('Open',  row.get('open',  0))),
                    'high':   _v(row.get('High',  row.get('high',  0))),
                    'low':    _v(row.get('Low',   row.get('low',   0))),
                    'close':  _v(row.get('Close', row.get('close', 0))),
                    'volume': _v(row.get('Volume',row.get('volume',0))),
                })
            except Exception as row_err:
                log.debug(f"Row parse error {symbol} {ts}: {row_err}")
                continue

        log.debug(f"Fetched {len(result)} bars for {symbol} {timeframe}")
        return result

    except Exception as e:
        log.error(f"Data fetch error for {symbol}: {e}")
        return []


def get_dxy_bias() -> str:
    """Fetch DXY and determine bias: bullish / bearish / neutral."""
    try:
        bars = fetch_bars('DXY', '15m', 20)
        if len(bars) < 5:
            return 'neutral'

        closes = [b['close'] for b in bars[-10:]]
        ma = np.mean(closes)
        current = closes[-1]

        if current > ma * 1.001:
            return 'bullish'
        elif current < ma * 0.999:
            return 'bearish'
        return 'neutral'
    except Exception as e:
        log.error(f"DXY error: {e}")
        return 'neutral'


def compute_atr(bars: list, period: int = 14) -> float:
    if len(bars) < period + 1:
        return 0.0
    trs = []
    for i in range(1, len(bars)):
        h, l, pc = bars[i]['high'], bars[i]['low'], bars[i-1]['close']
        trs.append(max(h - l, abs(h - pc), abs(l - pc)))
    return float(np.mean(trs[-period:]))


def compute_avg_volume(bars: list, period: int = 20) -> float:
    vols = [b['volume'] for b in bars[-period:] if b['volume'] > 0]
    return float(np.mean(vols)) if vols else 0.0

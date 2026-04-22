"""
Alert Bot Configuration
Standalone — works WITHOUT Interactive Brokers connection.
Uses yfinance for free market data.
"""

ALERT_CONFIG = {
    # ── Telegram ──────────────────────────────────────────────────────────────
    'telegram': {
        'bot_token': '8266836751:AAE9fzIWCfPJE-BK-eRdjGw_DRkcQICjGYY',   # from @BotFather
        'chat_id': '8741359827',     # from @userinfobot
    },

    # ── Data source (free, no broker needed) ─────────────────────────────────
    'data': {
        'provider': 'yfinance',               # free — no API key needed
        'symbols': {
            'XAUUSD': 'GC=F',                 # Gold futures (proxy)
            'XAGUSD': 'SI=F',                 # Silver futures (proxy)
            'DXY':    'DX-Y.NYB',             # US Dollar Index
        },
        'timeframes': ['3m', '5m', '15m'],
        'bars': 120,
    },

    # ── Strategy ──────────────────────────────────────────────────────────────
    'strategy': {
        'sr_lookback_bars': 100,
        'sr_touch_threshold': 0.001,
        'sweep_wick_ratio': 0.6,
        'volume_multiplier': 1.3,
        'volume_lookback': 20,
        'gold_confirmation_candles': 3,
        'silver_confirmation_candles': 3,   # relaxed — silver moves faster
        'blackout_minutes': 15,

        # ── Per-symbol overrides ───────────────────────────────────────────
        # Silver is ~3x more volatile than Gold — wider stops, wider S/R zone
        'XAUUSD': {
            'sr_touch_threshold':  0.0010,  # 0.10% touch zone
            'atr_stop_multiplier': 1.5,
            'rr_ratio':            2.0,
            'min_score':           55,  # middle ground
            'inst_required':       2,   # needs 2/4 institutional
        },
        'XAGUSD': {
            'sr_touch_threshold':  0.0020,  # 0.20% touch zone — silver less precise
            'atr_stop_multiplier': 2.0,     # wider stop — silver spikes
            'rr_ratio':            2.5,     # higher RR target to compensate wider stop
            'min_score':           60,  # higher bar for silver
            'inst_required':       1,   # only needs 1/4 — silver less liquid
        },
    },

    # ── Risk (for alert message calculations) ────────────────────────────────
    'risk': {
        'starting_capital': 350,
        'risk_per_trade_pct': 0.05,
        'atr_stop_multiplier': 1.5,
        'rr_ratio': 2.0,
    },

    # ── Alert cooldown (prevent duplicate alerts) ────────────────────────────
    'cooldown_minutes': 15,
}

# Add this block to your existing alert_config.py
# ── TradingView / Gmail ───────────────────────────────────────────────────────
TRADINGVIEW_CONFIG = {
    'gmail_address':      'YOUR_GMAIL_HERE@gmail.com',
    'gmail_app_password': 'YOUR_APP_PASSWORD_HERE',
}

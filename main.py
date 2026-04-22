"""
Alert Bot — Complete Version
✅ All 4 sessions
✅ News monitoring (Reuters, Dow Jones, Trading Economics, MoneyControl)
✅ Geopolitical alerts (instant — runs every 2 minutes in background)
✅ Volatility detector (auto-widens TP during big moves)
✅ Manual bias override via Telegram commands
✅ eToro cost calculations
✅ Signal scoring (volume as score not gate)
"""

import time
import logging
import sys
from datetime import datetime, timezone, time as dtime

from alert_config import ALERT_CONFIG
from telegram_alerter import TelegramAlerter
from signal_scanner import SignalScanner
from news_aggregator import NewsAggregator
from etoro_costs import EToroCalculator, format_cost_summary
from volatility_detector import VolatilityDetector, format_volatility_line
from geo_monitor import GeoNewsMonitor
from bias_controller import BiasController

try:
    from gmail_reader import GmailReader
    GMAIL_AVAILABLE = True
except ImportError:
    GMAIL_AVAILABLE = False

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(name)s | %(message)s',
    handlers=[
        logging.FileHandler('alert_bot.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
log = logging.getLogger('ALERT.MAIN')

SESSIONS = [
    # Blackout = first 15 min after open (news/spread spike — skip)
    # All times UTC
    {'name': 'Tokyo',    'open': dtime(0,  0), 'close': dtime(9,  0), 'blackout_end': dtime(0, 15), 'emoji': '🇯🇵'},
    {'name': 'China',    'open': dtime(1, 30), 'close': dtime(8,  0), 'blackout_end': dtime(1, 45), 'emoji': '🇨🇳'},
    {'name': 'London',   'open': dtime(8,  0), 'close': dtime(17, 0), 'blackout_end': dtime(8, 15), 'emoji': '🇬🇧'},
    {'name': 'New York', 'open': dtime(13, 0), 'close': dtime(22, 0), 'blackout_end': dtime(13,15), 'emoji': '🇺🇸'},
]

FRIDAY_CLOSE_UTC = dtime(20, 0)
SCAN_INTERVAL    = 3 * 60  # scan every 3 minutes


def berlin_time(utc_hour, utc_min=0):
    """Convert UTC hour to Berlin time string (CET=+1, CEST=+2 in summer)."""
    import time as _t
    offset = 2 if _t.localtime().tm_isdst else 1
    h = (utc_hour + offset) % 24
    return f"{h:02d}:{utc_min:02d}"

def get_live_sessions(t):
    return [s for s in SESSIONS if s['open'] <= t < s['close'] and t >= s['blackout_end']]

def get_blackout_sessions(t):
    return [s for s in SESSIONS if s['open'] <= t < s['blackout_end']]


class AlertBot:
    def __init__(self):
        cfg = ALERT_CONFIG

        # Core components
        self.telegram  = TelegramAlerter(cfg['telegram']['bot_token'], cfg['telegram']['chat_id'])
        self.scanner   = SignalScanner(cfg)
        self.news      = NewsAggregator()
        self.costs     = EToroCalculator()
        self.vol       = VolatilityDetector()
        self.capital   = cfg['risk']['starting_capital']
        self.cooldown  = cfg['cooldown_minutes'] * 60

        # Geopolitical monitor — runs every 2 minutes in background thread
        self.geo = GeoNewsMonitor(self.telegram, check_interval=120)
        self.geo.start()
        log.info("Geopolitical monitor started")

        # Bias controller — listens for Telegram commands
        self.bias = BiasController(
            cfg['telegram']['bot_token'],
            cfg['telegram']['chat_id']
        )
        self.bias.start()
        log.info("Bias controller started — send /status to your bot anytime")

        # Gmail / TradingView (optional)
        self.gmail = None
        if GMAIL_AVAILABLE:
            tv_cfg = cfg.get('tradingview', {})
            if tv_cfg.get('gmail_address') and tv_cfg.get('gmail_app_password'):
                self.gmail = GmailReader(
                    tv_cfg['gmail_address'],
                    tv_cfg['gmail_app_password']
                )
                log.info(f"Gmail reader active: {tv_cfg['gmail_address']}")

        self._last_alert = {}
        self._last_day   = None
        self._positions  = set()

    def run(self):
        log.info("Alert Bot starting — Complete Version")
        self.telegram.send_startup(self.capital)
        log.info("Send /status to your Telegram bot anytime to check state")
        log.info("Send /buy_only or /sell_only to set bias")

        while True:
            try:
                self._tick()
            except Exception as e:
                log.error(f"Tick error: {e}", exc_info=True)
            time.sleep(SCAN_INTERVAL)

    def _tick(self):
        now = datetime.now(timezone.utc)
        t   = now.time().replace(tzinfo=None)
        wd  = now.weekday()

        # Daily reset
        today = now.date()
        if today != self._last_day:
            self._last_day = today
            self.bias.alerts_sent = 0
            log.info("New day — counters reset.")

        # Weekend
        if wd >= 5:
            log.info("Weekend — sleeping.")
            return

        # Friday EOD
        if wd == 4 and t >= FRIDAY_CLOSE_UTC:
            if self._positions:
                for sym in list(self._positions):
                    self.telegram.send_close_reminder(sym, 'FRIDAY_EOD')
                    self._positions.discard(sym)
            return

        # Session check
        live     = get_live_sessions(t)
        blackout = get_blackout_sessions(t)

        if blackout and not live:
            log.info(f"Blackout: {[s['name'] for s in blackout]}")
        elif not live:
            log.info("No active session — sleeping.")

        # Gmail check
        if self.gmail:
            try:
                for tv_sig in self.gmail.check_for_alerts():
                    self._process_tv_signal(tv_sig, live)
            except Exception as e:
                log.error(f"Gmail error: {e}")

        if not live:
            return

        _now_utc = datetime.now(timezone.utc)
        _mo, _day = _now_utc.month, _now_utc.day
        _is_summer = (_mo > 3 and _mo < 10) or (_mo == 3 and _day >= 29) or (_mo == 10 and _day < 25)
        berlin_off = 2 if _is_summer else 1
        now_b = f"{(_now_utc.hour + berlin_off) % 24:02d}:{_now_utc.minute:02d}"
        log.info(f"Active: {[s['name'] for s in live]} — {now_b} Berlin — scanning...")

        # News status
        news_status = self.news.check_news_risk()
        log.info(f"News: {news_status['risk_level']} — {news_status['reason'][:50]}")

        # Scan signals
        signals = self.scanner.scan()
        for sig in signals:
            sig['active_sessions'] = live
            sig['news_status']     = news_status
            sig['source']          = 'yfinance'
            self._process_signal(sig)

    def _process_signal(self, sig: dict):
        symbol    = sig['symbol']
        direction = sig['direction']

        # Bias check
        if not self.bias.should_fire(direction):
            return

        # Cooldown
        if time.time() - self._last_alert.get(symbol, 0) < self.cooldown:
            log.info(f"{symbol}: Cooldown active.")
            return

        # Volatility analysis
        regime = self.vol.analyse(symbol)
        vol_line = format_volatility_line(regime)

        # Adjust targets based on volatility
        order = sig['order']
        adjusted = self.vol.adjust_targets(
            entry      = sig['entry_price'],
            stop_loss  = order['stop_loss'],
            direction  = direction,
            regime     = regime,
        )
        order['take_profit'] = adjusted['take_profit']
        order['rr_ratio']    = adjusted['rr_ratio']
        sig['vol_line']      = vol_line
        sig['vol_regime']    = regime['regime']

        # eToro costs
        action    = 'BUY' if direction == 'bullish' else 'SELL'
        cost_data = self.costs.calculate(
            symbol      = symbol,
            action      = action,
            entry_price = sig['entry_price'],
            stop_loss   = order['stop_loss'],
            take_profit = order['take_profit'],
            quantity    = order['etoro_units'],
            capital_eur = self.capital,
        )
        sig['cost_summary']  = format_cost_summary(cost_data)
        order['adjusted_tp'] = cost_data['adjusted_tp']
        order['net_rr']      = cost_data['net_rr']

        # Send
        sent = self.telegram.send_signal(sig, order)
        if sent:
            log.info(f"✅ Alert: {symbol} {direction.upper()} vol={regime['regime']} bias={self.bias.bias}")
            self._last_alert[symbol] = time.time()
            self._positions.add(symbol)
            self.bias.register_alert()

    def _process_tv_signal(self, tv_sig: dict, live: list):
        """Handle TradingView email signal."""
        symbol = tv_sig['symbol']
        if time.time() - self._last_alert.get(f"tv_{symbol}", 0) < self.cooldown:
            return

        from data_fetcher import fetch_bars, compute_atr
        bars  = fetch_bars(symbol, '5m', 30)
        atr   = compute_atr(bars) if bars else 5.0
        price = tv_sig['price']
        direction  = tv_sig['direction']
        stop_dist  = atr * ALERT_CONFIG['risk']['atr_stop_multiplier']
        risk_eur   = self.capital * ALERT_CONFIG['risk']['risk_per_trade_pct']

        regime   = self.vol.analyse(symbol, bars)
        adjusted = self.vol.adjust_targets(price, price - stop_dist if direction == 'bullish'
                                           else price + stop_dist, direction, regime)

        sig = {
            'symbol':          symbol,
            'direction':       direction,
            'entry_price':     round(price, 4),
            'level':           round(price, 4),
            'level_type':      'support' if direction == 'bullish' else 'resistance',
            'trend_15m':       'N/A',
            'dxy_bias':        'neutral',
            'volume_ratio':    0,
            'signal_score':    80,
            'signal_quality':  '⭐⭐ TradingView',
            'signal_notes':    ['TradingView Pine Script alert'],
            'atr':             round(atr, 4),
            'active_sessions': live,
            'news_status':     self.news.check_news_risk(),
            'source':          'tradingview',
            'vol_line':        format_volatility_line(regime),
            'vol_regime':      regime['regime'],
            'order': {
                'stop_loss':   round(price - stop_dist if direction == 'bullish' else price + stop_dist, 4),
                'take_profit': adjusted['take_profit'],
                'rr_ratio':    adjusted['rr_ratio'],
                'risk_eur':    round(risk_eur, 2),
                'risk_pct':    ALERT_CONFIG['risk']['risk_per_trade_pct'] * 100,
                'etoro_units': round(risk_eur / stop_dist, 2) if stop_dist > 0 else 0.01,
                'adjusted_tp': adjusted['take_profit'],
                'net_rr':      adjusted['rr_ratio'],
            }
        }

        if self.bias.should_fire(direction):
            sent = self.telegram.send_signal(sig, sig['order'])
            if sent:
                self._last_alert[f"tv_{symbol}"] = time.time()
                self.bias.register_alert()


if __name__ == '__main__':
    if (ALERT_CONFIG['telegram']['bot_token'] == 'YOUR_BOT_TOKEN_HERE'
            or ALERT_CONFIG['telegram']['chat_id'] == 'YOUR_CHAT_ID_HERE'):
        print("\nConfigure Telegram credentials in alert_config.py first.\n")
        sys.exit(1)
    bot = AlertBot()
    bot.run()

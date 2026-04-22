import logging
import urllib.request
import json
from datetime import datetime, timezone

log = logging.getLogger('ALERT.TELEGRAM')


class TelegramAlerter:
    def __init__(self, bot_token, chat_id):
        self.bot_token = bot_token
        self.chat_id   = chat_id
        self.base_url  = f"https://api.telegram.org/bot{bot_token}"

    def send(self, message):
        url  = f"{self.base_url}/sendMessage"
        data = {
            'chat_id':                  self.chat_id,
            'text':                     message,
            'parse_mode':               'HTML',
            'disable_web_page_preview': True,
        }
        return self._post(url, data)

    def send_signal(self, signal, order):
        direction      = signal['direction'].upper()
        symbol_display = signal['symbol'].replace('XAU','Gold ').replace('XAG','Silver ')
        action_emoji   = 'G' if direction == 'BULLISH' else 'R'
        action_emoji   = '\U0001f7e2' if direction == 'BULLISH' else '\U0001f534'
        trade_action   = 'BUY' if direction == 'BULLISH' else 'SELL'
        now_utc        = datetime.now(timezone.utc)
        # Berlin = UTC+1 winter, UTC+2 summer
        # DST starts last Sunday of March, ends last Sunday of October
        # Hardcoded logic — does not rely on PC timezone
        _mo, _day = now_utc.month, now_utc.day
        _is_summer = (_mo > 3 and _mo < 10) or                      (_mo == 3 and _day >= 29) or                      (_mo == 10 and _day < 25)
        berlin_offset  = 2 if _is_summer else 1
        now_berlin     = now_utc.hour + berlin_offset
        now            = f"{now_utc.strftime('%H:%M')} UTC  ({now_berlin % 24:02d}:{now_utc.strftime('%M')} Berlin)"
        source         = signal.get('source','scanner')
        source_label   = 'TradingView' if source == 'tradingview' else 'Bot Scanner'

        sessions    = signal.get('active_sessions', [])
        session_str = ' + '.join(f"{s['emoji']} {s['name']}" for s in sessions) if sessions else 'Market'

        dxy      = signal.get('dxy_bias','neutral')
        dxy_line = ''
        if dxy == 'bullish':
            dxy_line = '\nDXY: Strong USD (headwind)'
        elif dxy == 'bearish':
            dxy_line = '\nDXY: Weak USD (tailwind)'

        quality = signal.get('signal_quality','')
        score   = signal.get('signal_score', 0)
        notes   = ' | '.join(signal.get('signal_notes',[]))

        vol_line   = signal.get('vol_line','')
        vol_regime = signal.get('vol_regime','normal')
        vol_warn   = '\nHIGH VOLATILITY - TP widened automatically' if vol_regime in ('high','extreme') else ''

        news      = signal.get('news_status', {})
        news_risk = news.get('risk_level','CLEAR')
        if news_risk == 'HIGH':
            news_block = (
                "\n-----\n"
                "NEWS: HIGH RISK\n"
                f"{news.get('source','')}: {news.get('reason','')[:60]}...\n"
                "Trade carefully."
            )
        elif news_risk == 'MEDIUM':
            news_block = f"\nNEWS: MEDIUM RISK - {news.get('reason','')[:50]}..."
        else:
            news_block = '\nNews: Clear'

        cost_summary = signal.get('cost_summary','')
        adj_tp       = order.get('adjusted_tp', order['take_profit'])
        net_rr       = order.get('net_rr', order['rr_ratio'])

        inst_summary = signal.get('inst_summary','')
        s_vwap = signal.get('session_vwap', 0)
        d_vwap = signal.get('daily_vwap', 0)
        poc    = signal.get('poc', 0)
        va_h   = signal.get('va_high', 0)
        va_l   = signal.get('va_low', 0)

        key_levels = ''
        if poc:
            key_levels = (
                f"\nKey Levels:\n"
                f"  VWAP session:{s_vwap:.2f} daily:{d_vwap:.2f}\n"
                f"  POC:{poc:.2f}  VA:{va_l:.2f}-{va_h:.2f}"
            )

        sep = "\u2501" * 20

        # Signal tier from scanner
        signal_tier  = signal.get('signal_tier', '⭐ RELAXED')
        tier_note    = signal.get('tier_note', '')
        is_silver    = signal.get('is_silver', False)
        correlated   = signal.get('correlated', False)
        corr_note    = signal.get('correlation_note', '')
        tier_bg     = (
            '\U0001f7e2' if 'STRONG'   in signal_tier else
            '\U0001f7e1' if 'STANDARD' in signal_tier else
            '\U0001f7e0'
        )
        # Silver context
        silver_note = ''
        if is_silver:
            silver_note = '\n\U0001f4a1 <i>Silver: wider stop (2x ATR), target 2.5R — normal for XAG</i>'
        # Correlation badge
        corr_line = ''
        if correlated:
            corr_line = f'\n\U0001f517 <b>CORRELATION:</b> <i>{corr_note}</i>'


        msg = (
            f"{action_emoji} <b>TRADE ALERT - {symbol_display}</b>\n"
            f"{sep}\n"
            f"{tier_bg} <b>TIER: {signal_tier}</b>\n"
            f"<i>{tier_note}</i>\n"
            f"{sep}\n"
            f"<b>Time:</b> {now}\n"
            f"<b>Session:</b> {session_str}\n"
            f"<b>Action:</b> <b>{trade_action}</b>\n"
            f"{sep}\n"
            f"<b>Entry:</b> {signal['entry_price']:.4f}\n"
            f"<b>Stop Loss:</b> {order['stop_loss']:.4f}\n"
            f"<b>Take Profit:</b> {adj_tp:.4f}\n"
            f"<b>Risk/Reward:</b> 1:{net_rr}\n"
            f"<b>Risk:</b> EUR{order['risk_eur']:.2f} ({order['risk_pct']:.0f}% of account)\n"
            f"{sep}\n"
            f"<b>Score:</b> {score}/100 | <b>Pattern:</b> {notes}\n"
            f"<b>15m Trend:</b> {signal.get('trend_15m','N/A').title()}{dxy_line}\n"
            f"{vol_line}{vol_warn}\n"
            f"{sep}\n"
            f"{inst_summary}"
            f"{key_levels}\n"
            f"{sep}\n"
            f"{cost_summary}\n"
            f"<b>eToro size:</b> {order['etoro_units']} units\n"
            f"{news_block}\n"
            f"{sep}\n"
            f"{silver_note}\n" if silver_note else ""
            f"{corr_line}\n" if corr_line else ""
            f"<i>⭐⭐⭐ STRONG = take it  ⭐⭐ STANDARD = good  ⭐ RELAXED = be selective</i>\n"
            f"<i>/buy_only /sell_only /both /pause /status</i>"
        )
        return self.send(msg)

    def send_close_reminder(self, symbol, reason):
        emoji    = {'FRIDAY_EOD':'P','MAX_HOLD_48H':'T'}.get(reason,'W')
        sym_disp = symbol.replace('XAU','Gold ').replace('XAG','Silver ')
        return self.send(
            f"CLOSE POSITION - {sym_disp}\n"
            f"Reason: {reason.replace('_',' ')}\n"
            f"Close manually on eToro now."
        )

    def send_startup(self, capital):
        now = datetime.now(timezone.utc).strftime('%A %H:%M UTC')
        sep = "\u2501" * 20
        return self.send(
            f"<b>Alert Bot - Complete Version</b>\n"
            f"{sep}\n"
            f"{now}\n"
            f"Account: EUR{capital:.0f}\n"
            f"{sep}\n"
            f"🇯🇵 Tokyo:    01:15-10:00 Berlin  (00:15-09:00 UTC)\n"
            f"🇨🇳 China:    02:45-09:00 Berlin  (01:45-08:00 UTC)\n"
            f"🇬🇧 London:   09:15-18:00 Berlin  (08:15-17:00 UTC)\n"
            f"🇺🇸 New York: 14:15-23:00 Berlin  (13:15-22:00 UTC)\n"
            f"{sep}\n"
            f"Geopolitical alerts: ON (2min)\n"
            f"Volatility detector: ON (auto TP)\n"
            f"Institutional indicators: ON (2/4 min, tiered)\n"
            f"Scan: every 3min | Signals: 3m candles | S/R: 15m\n"
            f"  - Liquidity Sweep\n"
            f"  - Order Flow Imbalance\n"
            f"  - Volume Profile + POC\n"
            f"  - Anchored VWAP\n"
            f"eToro cost calculations: ON\n"
            f"{sep}\n"
            f"Commands:\n"
            f"/buy_only  /sell_only  /both\n"
            f"/pause  /resume  /status"
        )

    def test(self):
        return self.send("Alert Bot Connected. All systems active.")

    def _post(self, url, data):
        try:
            payload = json.dumps(data).encode('utf-8')
            req     = urllib.request.Request(url, data=payload,
                          headers={'Content-Type': 'application/json'})
            with urllib.request.urlopen(req, timeout=10) as resp:
                result = json.loads(resp.read().decode())
                if not result.get('ok'):
                    log.error(f"Telegram error: {result}")
                    return False
                return True
        except Exception as e:
            log.error(f"Telegram send failed: {e}")
            return False

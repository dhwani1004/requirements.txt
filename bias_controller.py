"""
Manual Bias Override
Lets you control the bot via Telegram commands.
Send a message to your bot to change its behaviour instantly.

Commands:
  /buy_only     — Bot only fires BUY signals today
  /sell_only    — Bot only fires SELL signals today
  /both         — Bot fires both BUY and SELL (default)
  /pause        — Pause all signals temporarily
  /resume       — Resume signals
  /status       — Show current bot status
  /stats        — Show today's alert count and settings
"""

import logging
import urllib.request
import json
import threading
import time
from datetime import datetime, timezone

log = logging.getLogger('ALERT.BIAS')


class BiasController:
    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id   = chat_id
        self.base_url  = f"https://api.telegram.org/bot{bot_token}"

        # Current state
        self.bias       = 'both'    # 'buy_only' | 'sell_only' | 'both'
        self.paused     = False
        self.last_update_id = 0

        # Stats
        self.alerts_sent   = 0
        self.start_time    = datetime.now(timezone.utc)

        self._running = False
        self._thread  = None

    def start(self):
        """Start listening for Telegram commands in background."""
        self._running = True
        self._thread  = threading.Thread(target=self._poll_loop, daemon=True)
        self._thread.start()
        log.info("Bias controller started — listening for Telegram commands")

    def stop(self):
        self._running = False

    def should_fire(self, direction: str) -> bool:
        """
        Check if a signal should fire given current bias.
        direction: 'bullish' or 'bearish'
        """
        if self.paused:
            log.info("Bot is paused — signal blocked")
            return False

        if self.bias == 'buy_only' and direction == 'bearish':
            log.info("Bias is BUY ONLY — SELL signal blocked")
            return False

        if self.bias == 'sell_only' and direction == 'bullish':
            log.info("Bias is SELL ONLY — BUY signal blocked")
            return False

        return True

    def register_alert(self):
        self.alerts_sent += 1

    def _poll_loop(self):
        """Poll Telegram for new commands every 3 seconds."""
        while self._running:
            try:
                self._check_commands()
            except Exception as e:
                log.debug(f"Command poll error: {e}")
            time.sleep(3)

    def _check_commands(self):
        url    = f"{self.base_url}/getUpdates"
        params = f"?offset={self.last_update_id + 1}&timeout=2&allowed_updates=[\"message\"]"

        req = urllib.request.Request(url + params)
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())

        if not data.get('ok') or not data.get('result'):
            return

        for update in data['result']:
            self.last_update_id = update['update_id']
            msg = update.get('message', {})
            text = msg.get('text', '').strip().lower()
            chat = str(msg.get('chat', {}).get('id', ''))

            # Only respond to commands from your own chat
            if chat != str(self.chat_id):
                continue

            self._handle_command(text)

    def _handle_command(self, text: str):
        now = datetime.now(timezone.utc).strftime('%H:%M UTC')

        if text == '/buy_only':
            self.bias   = 'buy_only'
            self.paused = False
            self._reply(
                f"✅ <b>Bias set: BUY ONLY</b>\n"
                f"🕐 {now}\n"
                f"Bot will only fire BUY (bullish) signals.\n"
                f"All SELL signals blocked.\n\n"
                f"<i>Send /both to return to normal.</i>"
            )
            log.info("Bias set to BUY ONLY via Telegram command")

        elif text == '/sell_only':
            self.bias   = 'sell_only'
            self.paused = False
            self._reply(
                f"✅ <b>Bias set: SELL ONLY</b>\n"
                f"🕐 {now}\n"
                f"Bot will only fire SELL (bearish) signals.\n"
                f"All BUY signals blocked.\n\n"
                f"<i>Send /both to return to normal.</i>"
            )
            log.info("Bias set to SELL ONLY via Telegram command")

        elif text == '/both':
            self.bias   = 'both'
            self.paused = False
            self._reply(
                f"✅ <b>Bias: BOTH directions</b>\n"
                f"🕐 {now}\n"
                f"Bot will fire both BUY and SELL signals normally."
            )
            log.info("Bias reset to BOTH via Telegram command")

        elif text == '/pause':
            self.paused = True
            self._reply(
                f"⏸ <b>Bot PAUSED</b>\n"
                f"🕐 {now}\n"
                f"No signals will fire until you send /resume."
            )
            log.info("Bot paused via Telegram command")

        elif text == '/resume':
            self.paused = False
            self._reply(
                f"▶️ <b>Bot RESUMED</b>\n"
                f"🕐 {now}\n"
                f"Scanning normally. Bias: {self.bias.upper()}"
            )
            log.info("Bot resumed via Telegram command")

        elif text == '/status':
            uptime = (datetime.now(timezone.utc) - self.start_time)
            hours  = int(uptime.total_seconds() // 3600)
            mins   = int((uptime.total_seconds() % 3600) // 60)
            status = '⏸ PAUSED' if self.paused else '▶️ RUNNING'
            bias_display = {
                'both':      '↕️ Both BUY and SELL',
                'buy_only':  '⬆️ BUY only',
                'sell_only': '⬇️ SELL only',
            }.get(self.bias, self.bias)

            self._reply(
                f"📊 <b>Bot Status</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"Status:   {status}\n"
                f"Bias:     {bias_display}\n"
                f"Alerts:   {self.alerts_sent} sent today\n"
                f"Uptime:   {hours}h {mins}m\n"
                f"Time:     {datetime.now(timezone.utc).strftime('%H:%M UTC')}\n"
                f"━━━━━━━━━━━━━━━━━━━━\n"
                f"<b>Commands:</b>\n"
                f"/buy_only — BUY signals only\n"
                f"/sell_only — SELL signals only\n"
                f"/both — both directions\n"
                f"/pause — pause all signals\n"
                f"/resume — resume signals\n"
                f"/status — this message"
            )

        elif text.startswith('/'):
            self._reply(
                f"❓ Unknown command: {text}\n\n"
                f"Available commands:\n"
                f"/buy_only | /sell_only | /both\n"
                f"/pause | /resume | /status"
            )

    def _reply(self, message: str):
        try:
            url  = f"{self.base_url}/sendMessage"
            data = {
                'chat_id':    self.chat_id,
                'text':       message,
                'parse_mode': 'HTML',
            }
            payload = json.dumps(data).encode('utf-8')
            req     = urllib.request.Request(
                url, data=payload,
                headers={'Content-Type': 'application/json'}
            )
            urllib.request.urlopen(req, timeout=5)
        except Exception as e:
            log.error(f"Reply failed: {e}")

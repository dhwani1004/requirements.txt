"""
Gmail Reader
Watches your Gmail inbox for TradingView alert emails.
When detected — fires Telegram signal with full trade details.

Uses Gmail IMAP — no API key needed, just Gmail App Password.
Checks every 5 minutes alongside the existing yfinance scanner.
"""

import imaplib
import email
import logging
import time
import re
from datetime import datetime, timezone, timedelta
from email.header import decode_header

log = logging.getLogger('ALERT.GMAIL')

# TradingView sends alerts from this address
TRADINGVIEW_SENDER = 'noreply@tradingview.com'

# Our alert message format from Pine Script:
# ALERTBOT|BUY|XAUUSD|2341.50|2024-01-15T09:14:00
ALERT_PREFIX = 'ALERTBOT|'


class GmailReader:
    def __init__(self, email_address: str, app_password: str):
        self.email_address = email_address
        self.app_password  = app_password
        self._last_checked = datetime.now(timezone.utc) - timedelta(minutes=10)
        self._seen_ids     = set()

    def check_for_alerts(self) -> list:
        """
        Connect to Gmail, find new TradingView alert emails.
        Returns list of parsed signal dicts.
        """
        signals = []
        try:
            mail = imaplib.IMAP4_SSL('imap.gmail.com', 993)
            mail.login(self.email_address, self.app_password)
            mail.select('inbox')

            # Search for unread emails from TradingView
            status, messages = mail.search(None, 
                f'(UNSEEN FROM "{TRADINGVIEW_SENDER}")')

            if status != 'OK' or not messages[0]:
                mail.logout()
                return []

            email_ids = messages[0].split()
            log.info(f"Found {len(email_ids)} new TradingView email(s)")

            for eid in email_ids:
                if eid in self._seen_ids:
                    continue

                # Fetch email
                status, msg_data = mail.fetch(eid, '(RFC822)')
                if status != 'OK':
                    continue

                msg = email.message_from_bytes(msg_data[0][1])

                # Get subject and body
                subject = _decode_header(msg.get('Subject', ''))
                body    = _get_body(msg)

                log.info(f"TradingView email: {subject[:60]}")

                # Parse alert
                signal = _parse_alert(subject, body)
                if signal:
                    signals.append(signal)
                    self._seen_ids.add(eid)
                    log.info(f"Parsed signal: {signal}")

                # Mark as read
                mail.store(eid, '+FLAGS', '\\Seen')

            mail.logout()

        except imaplib.IMAP4.error as e:
            log.error(f"Gmail IMAP error: {e}")
        except Exception as e:
            log.error(f"Gmail check failed: {e}")

        return signals


def _parse_alert(subject: str, body: str) -> dict:
    """
    Parse TradingView alert email into signal dict.
    Expected format: ALERTBOT|BUY|XAUUSD|2341.50|timestamp
    """
    # Try body first, then subject
    text = body.strip() if body else subject

    if ALERT_PREFIX not in text:
        log.debug(f"Not a bot alert: {text[:50]}")
        return None

    try:
        # Extract the ALERTBOT| line
        for line in text.split('\n'):
            if ALERT_PREFIX in line:
                text = line.strip()
                break

        parts = text.split('|')
        if len(parts) < 4:
            log.warning(f"Malformed alert: {text}")
            return None

        _, action, ticker, price_str = parts[:4]
        price = float(price_str)

        # Map ticker to our symbol format
        symbol_map = {
            'XAUUSD': 'XAUUSD',
            'XAGUSD': 'XAGUSD',
            'GOLD':   'XAUUSD',
            'SILVER': 'XAGUSD',
            'GC1!':   'XAUUSD',
            'SI1!':   'XAGUSD',
        }
        symbol = symbol_map.get(ticker.upper(), ticker.upper())

        return {
            'source':    'tradingview',
            'symbol':    symbol,
            'action':    action.upper(),
            'direction': 'bullish' if action.upper() == 'BUY' else 'bearish',
            'price':     price,
            'timestamp': datetime.now(timezone.utc).isoformat(),
        }

    except Exception as e:
        log.error(f"Alert parse error: {e} | text: {text[:80]}")
        return None


def _decode_header(value: str) -> str:
    """Decode email header."""
    try:
        parts = decode_header(value)
        decoded = []
        for part, encoding in parts:
            if isinstance(part, bytes):
                decoded.append(part.decode(encoding or 'utf-8', errors='replace'))
            else:
                decoded.append(str(part))
        return ' '.join(decoded)
    except Exception:
        return value


def _get_body(msg) -> str:
    """Extract plain text body from email."""
    try:
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == 'text/plain':
                    return part.get_payload(decode=True).decode('utf-8', errors='replace')
        else:
            return msg.get_payload(decode=True).decode('utf-8', errors='replace')
    except Exception:
        return ''
    return ''

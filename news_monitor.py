"""
News Monitor
Scrapes headlines from: Reuters, Trading Economics, MoneyControl
Flags high-impact economic events that should pause trading.
No API keys needed — free scraping only.
"""

import logging
import urllib.request
import urllib.parse
import json
import re
from datetime import datetime, timezone, timedelta
from typing import List, Optional

log = logging.getLogger('ALERT.NEWS')

# ── High-impact keywords that should pause trading ────────────────────────────
HIGH_IMPACT_KEYWORDS = [
    # Fed / Central Banks
    'federal reserve', 'fed rate', 'fomc', 'powell', 'interest rate decision',
    'rate hike', 'rate cut', 'basis points', 'bps',
    # Economic data
    'non-farm payroll', 'nfp', 'jobs report', 'unemployment',
    'cpi', 'inflation', 'pce', 'gdp', 'retail sales',
    'ism manufacturing', 'ism services',
    # Gold/Silver specific
    'gold reserve', 'gold price', 'silver price', 'precious metals',
    'comex', 'bullion',
    # Geopolitical
    'war', 'sanctions', 'nuclear', 'crisis', 'emergency',
    'recession', 'default', 'collapse',
    # Dollar
    'dollar index', 'dxy', 'dollar strength', 'dollar weakness',
]

# ── Scheduled high-impact events (UTC times, recurring) ─────────────────────
# These are known recurring events — bot pauses 30min before and after
SCHEDULED_EVENTS = [
    # US data — typically 13:30 UTC (8:30am ET)
    {'name': 'NFP',         'day': 4, 'hour': 13, 'minute': 30},  # First Friday
    {'name': 'CPI',         'day': 1, 'hour': 13, 'minute': 30},  # Usually Tuesday
    {'name': 'FOMC',        'day': 2, 'hour': 19, 'minute': 0},   # Wednesday 2pm ET
    {'name': 'GDP',         'day': 2, 'hour': 13, 'minute': 30},
    {'name': 'Retail Sales','day': 1, 'hour': 13, 'minute': 30},
]


class NewsMonitor:
    def __init__(self):
        self._cache = {}          # url → (timestamp, content)
        self._cache_ttl = 300     # 5 minute cache
        self._last_headlines = [] # store for Telegram digest

    def is_safe_to_trade(self, minutes_buffer: int = 30) -> tuple:
        """
        Main method — returns (True/False, reason_string)
        True = safe to trade
        False = news blackout active
        """
        now = datetime.now(timezone.utc)

        # 1. Check scheduled events
        event = self._check_scheduled_events(now, minutes_buffer)
        if event:
            return False, f"Scheduled event: {event}"

        # 2. Check live headlines
        alerts = self._check_live_headlines()
        if alerts:
            return False, f"Breaking: {alerts[0]}"

        return True, "No high-impact news"

    def get_headlines_digest(self) -> str:
        """Return recent headlines for Telegram morning briefing."""
        headlines = []

        # Reuters
        reuters = self._fetch_reuters()
        if reuters:
            headlines += reuters[:3]

        # Trading Economics
        te = self._fetch_trading_economics()
        if te:
            headlines += te[:2]

        # MoneyControl
        mc = self._fetch_moneycontrol()
        if mc:
            headlines += mc[:2]

        if not headlines:
            return "No headlines available"

        return '\n'.join(f"• {h}" for h in headlines[:8])

    # ── Scheduled Event Check ─────────────────────────────────────────────────

    def _check_scheduled_events(self, now: datetime, buffer_min: int) -> Optional[str]:
        """Check if we're within buffer_min of any known high-impact event."""
        buffer = timedelta(minutes=buffer_min)

        for event in SCHEDULED_EVENTS:
            event_time = now.replace(
                hour=event['hour'],
                minute=event['minute'],
                second=0, microsecond=0
            )
            # Check if current time is within buffer before or after event
            if (event_time - buffer) <= now <= (event_time + buffer):
                return event['name']

        return None

    # ── Live Headline Scrapers ────────────────────────────────────────────────

    def _check_live_headlines(self) -> List[str]:
        """Check all sources for breaking high-impact news."""
        alerts = []

        try:
            reuters = self._fetch_reuters()
            for h in reuters:
                if self._is_high_impact(h):
                    alerts.append(h)
        except Exception as e:
            log.debug(f"Reuters check failed: {e}")

        try:
            te = self._fetch_trading_economics()
            for h in te:
                if self._is_high_impact(h):
                    alerts.append(h)
        except Exception as e:
            log.debug(f"Trading Economics check failed: {e}")

        return alerts

    def _fetch_reuters(self) -> List[str]:
        """Fetch Reuters markets headlines via RSS."""
        url = 'https://feeds.reuters.com/reuters/businessNews'
        return self._parse_rss(url, max_items=10)

    def _fetch_trading_economics(self) -> List[str]:
        """Fetch Trading Economics calendar via their public page."""
        try:
            url = 'https://tradingeconomics.com/calendar'
            html = self._get_url(url, timeout=8)
            if not html:
                return []

            # Extract event names from calendar table
            events = re.findall(r'<td[^>]*class="[^"]*event[^"]*"[^>]*>([^<]+)<', html)
            return [e.strip() for e in events[:10] if e.strip()]
        except Exception as e:
            log.debug(f"Trading Economics fetch error: {e}")
            return []

    def _fetch_moneycontrol(self) -> List[str]:
        """Fetch MoneyControl commodity headlines via RSS."""
        url = 'https://www.moneycontrol.com/rss/commodities.xml'
        return self._parse_rss(url, max_items=8)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _parse_rss(self, url: str, max_items: int = 10) -> List[str]:
        """Parse RSS feed and extract titles."""
        try:
            xml = self._get_url(url, timeout=8)
            if not xml:
                return []
            titles = re.findall(r'<title><!\[CDATA\[(.+?)\]\]></title>', xml)
            if not titles:
                titles = re.findall(r'<title>(.+?)</title>', xml)
            # Skip feed title (first item)
            return [t.strip() for t in titles[1:max_items+1]]
        except Exception as e:
            log.debug(f"RSS parse error {url}: {e}")
            return []

    def _get_url(self, url: str, timeout: int = 8) -> Optional[str]:
        """Fetch URL with caching."""
        now = datetime.now(timezone.utc).timestamp()
        if url in self._cache:
            cached_time, cached_content = self._cache[url]
            if now - cached_time < self._cache_ttl:
                return cached_content

        try:
            req = urllib.request.Request(
                url,
                headers={
                    'User-Agent': 'Mozilla/5.0 (compatible; MarketBot/1.0)',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                }
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                content = resp.read().decode('utf-8', errors='ignore')
                self._cache[url] = (now, content)
                return content
        except Exception as e:
            log.debug(f"URL fetch failed {url}: {e}")
            return None

    def _is_high_impact(self, headline: str) -> bool:
        """Check if headline contains high-impact keywords."""
        hl_lower = headline.lower()
        return any(kw in hl_lower for kw in HIGH_IMPACT_KEYWORDS)

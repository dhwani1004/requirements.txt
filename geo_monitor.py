"""
Geopolitical News Monitor
Watches RSS feeds every 2 minutes (faster than main scan).
Fires INSTANT Telegram alert when war/crisis/sanctions headlines break.
Separate from the regular signal alerts.
"""

import logging
import urllib.request
import json
import threading
import time
from datetime import datetime, timezone, timedelta
from xml.etree import ElementTree as ET

log = logging.getLogger('ALERT.GEOPOL')

# Geopolitical keywords that move Gold significantly
GEOPOLITICAL_KEYWORDS = {
    'critical': [
        # War / Military
        'war declared', 'military strike', 'missile attack', 'airstrike',
        'invasion', 'troops deployed', 'nuclear', 'warship',
        'attack on', 'bombed', 'explosion',

        # Iran specific
        'iran attack', 'iran strike', 'iran nuclear', 'iran sanction',
        'strait of hormuz', 'iranian',

        # Russia/Ukraine
        'russia attack', 'ukraine war', 'nato response',
        'russian missile',

        # Middle East
        'israel attack', 'hamas', 'hezbollah', 'gaza escalat',
        'middle east war',

        # North Korea
        'north korea missile', 'kim jong', 'nuclear test',

        # China/Taiwan
        'taiwan strait', 'china taiwan', 'china invasion',
    ],
    'high': [
        # Sanctions
        'sanctions imposed', 'sanctions announced', 'new sanctions',
        'oil embargo', 'trade ban',

        # Economic crisis
        'bank collapse', 'banking crisis', 'financial crisis',
        'debt default', 'currency crisis', 'market crash',
        'emergency rate', 'fed emergency',

        # Geopolitical tension
        'ceasefire collapses', 'peace talks fail', 'diplomatic crisis',
        'expels ambassador', 'closes embassy',
        'conflict escalat', 'tensions escalat',
    ],
    'medium': [
        # Warnings / Developments
        'sanctions threatened', 'military exercises',
        'ceasefire', 'peace talks', 'diplomatic',
        'trade war', 'tariffs imposed',
        'opec cut', 'oil supply',
    ]
}

# News sources to monitor
GEO_FEEDS = [
    'https://feeds.reuters.com/reuters/worldNews',
    'https://feeds.reuters.com/Reuters/worldNews',
    'https://feeds.bbci.co.uk/news/world/rss.xml',
    'https://feeds.content.dowjones.io/public/rss/mw_realtimeheadlines',
]


class GeoNewsMonitor:
    def __init__(self, telegram_alerter, check_interval: int = 120):
        self.telegram        = telegram_alerter
        self.check_interval  = check_interval   # 2 minutes
        self._seen_headlines = set()
        self._running        = False
        self._thread         = None
        self._last_alert_time = {}   # keyword → timestamp (prevent spam)
        self._alert_cooldown  = 900  # 15 min between same-topic alerts

    def start(self):
        """Start monitoring in background thread."""
        self._running = True
        self._thread  = threading.Thread(target=self._monitor_loop, daemon=True)
        self._thread.start()
        log.info("Geopolitical news monitor started (checking every 2 minutes)")

    def stop(self):
        self._running = False
        log.info("Geopolitical news monitor stopped")

    def _monitor_loop(self):
        while self._running:
            try:
                self._check_feeds()
            except Exception as e:
                log.error(f"Geo monitor error: {e}")
            time.sleep(self.check_interval)

    def _check_feeds(self):
        now = datetime.now(timezone.utc)

        for feed_url in GEO_FEEDS:
            try:
                articles = self._fetch_feed(feed_url)
                for article in articles:
                    self._evaluate_article(article, now)
            except Exception as e:
                log.debug(f"Feed error ({feed_url[:40]}): {e}")

    def _evaluate_article(self, article: dict, now: datetime):
        title = article.get('title', '').lower()
        headline_id = hash(title[:50])

        # Skip already seen
        if headline_id in self._seen_headlines:
            return
        self._seen_headlines.add(headline_id)

        # Only consider articles from last 10 minutes
        pub_time = article.get('datetime')
        if pub_time:
            age = (now - pub_time).total_seconds()
            if age > 600:   # older than 10 minutes
                return

        # Check impact level
        impact, matched_kw = self._classify(title)
        if not impact:
            return

        # Cooldown per keyword
        last = self._last_alert_time.get(matched_kw, 0)
        if time.time() - last < self._alert_cooldown:
            return

        # Fire alert
        self._send_geo_alert(article, impact, matched_kw)
        self._last_alert_time[matched_kw] = time.time()

    def _classify(self, title: str):
        for kw in GEOPOLITICAL_KEYWORDS['critical']:
            if kw in title:
                return 'CRITICAL', kw
        for kw in GEOPOLITICAL_KEYWORDS['high']:
            if kw in title:
                return 'HIGH', kw
        for kw in GEOPOLITICAL_KEYWORDS['medium']:
            if kw in title:
                return 'MEDIUM', kw
        return None, None

    def _send_geo_alert(self, article: dict, impact: str, keyword: str):
        title   = article.get('title', '')[:100]
        source  = article.get('source', 'News')
        url     = article.get('url', '')
        now_str = datetime.now(timezone.utc).strftime('%H:%M UTC')

        if impact == 'CRITICAL':
            emoji    = '🚨🚨🚨'
            gold_msg = '⬆️ Gold likely SPIKING — consider BUY only mode'
            action   = 'IMMEDIATE ATTENTION REQUIRED'
        elif impact == 'HIGH':
            emoji    = '🚨'
            gold_msg = '⬆️ Gold likely moving — watch for direction'
            action   = 'Monitor closely'
        else:
            emoji    = '⚠️'
            gold_msg = '📊 May affect Gold — watch chart'
            action   = 'Be aware'

        message = (
            f"{emoji} <b>GEOPOLITICAL ALERT — {impact}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🕐 {now_str}\n"
            f"📰 <b>{source}:</b>\n"
            f"<b>{title}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"🥇 <b>Gold Impact:</b> {gold_msg}\n"
            f"📋 <b>Action:</b> {action}\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"<i>This is a news alert only — not a trade signal.</i>\n"
            f"<i>Wait for bot signal before entering any trade.</i>"
        )

        self.telegram.send(message)
        log.warning(f"Geo alert sent: [{impact}] {title[:60]}")

    def _fetch_feed(self, url: str) -> list:
        req = urllib.request.Request(
            url,
            headers={'User-Agent': 'Mozilla/5.0', 'Accept': 'application/rss+xml'}
        )
        with urllib.request.urlopen(req, timeout=6) as resp:
            content = resp.read().decode('utf-8', errors='replace')

        root     = ET.fromstring(content)
        items    = root.findall('.//item') or root.findall('.//{http://www.w3.org/2005/Atom}entry')
        articles = []
        now      = datetime.now(timezone.utc)

        for item in items[:15]:
            title    = _get_text(item, 'title') or ''
            link     = _get_text(item, 'link')  or ''
            pub_date = _get_text(item, 'pubDate') or ''
            dt       = _parse_date(pub_date) or now

            # Detect source from URL
            source = 'Reuters' if 'reuters' in url else \
                     'BBC'     if 'bbc'     in url else \
                     'Dow Jones' if 'dowjones' in url else 'News'

            articles.append({
                'title':    title.strip(),
                'url':      link.strip(),
                'source':   source,
                'datetime': dt,
            })

        return articles


def _get_text(element, tag):
    found = element.find(tag)
    return found.text.strip() if found is not None and found.text else ''


def _parse_date(date_str):
    if not date_str:
        return None
    formats = [
        '%a, %d %b %Y %H:%M:%S %z',
        '%a, %d %b %Y %H:%M:%S GMT',
        '%Y-%m-%dT%H:%M:%S%z',
        '%Y-%m-%dT%H:%M:%SZ',
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(date_str.strip(), fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    return None

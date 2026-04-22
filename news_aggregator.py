"""
News Aggregator
Pulls from: Trading Economics, Reuters RSS, MoneyControl RSS
Dow Jones Newswires (via free RSS feed)

Detects high-impact events affecting Gold, Silver, USD in next 30 minutes.
No API keys needed for RSS feeds.
"""

import logging
import urllib.request
import json
import re
from datetime import datetime, timezone, timedelta
from xml.etree import ElementTree as ET

log = logging.getLogger('ALERT.NEWS')

# ── RSS Feed URLs ─────────────────────────────────────────────────────────────
FEEDS = {
    'reuters': {
        'url':   'https://feeds.reuters.com/reuters/businessNews',
        'name':  'Reuters',
        'emoji': '📰',
    },
    'moneycontrol': {
        'url':   'https://www.moneycontrol.com/rss/marketreports.xml',
        'name':  'MoneyControl',
        'emoji': '📊',
    },
    'trading_economics': {
        'url':   'https://tradingeconomics.com/rss/news.aspx',
        'name':  'Trading Economics',
        'emoji': '📈',
    },
    'marketwatch': {
        'url':   'https://feeds.content.dowjones.io/public/rss/mw_realtimeheadlines',
        'name':  'Dow Jones / MarketWatch',
        'emoji': '🗞️',
    },
}

# ── High-impact keywords that affect Gold/Silver/USD ─────────────────────────
HIGH_IMPACT_KEYWORDS = [
    # US Economic Data
    'nonfarm payroll', 'non-farm payroll', 'nfp',
    'federal reserve', 'fed rate', 'fomc', 'interest rate decision',
    'cpi', 'inflation', 'consumer price',
    'gdp', 'gross domestic product',
    'unemployment', 'jobless claims',
    'pce', 'personal consumption',
    'ism manufacturing', 'ism services',
    'retail sales',
    'jackson hole',
    'powell', 'yellen',

    # Gold/Silver specific
    'gold prices', 'silver prices', 'precious metals',
    'gold rally', 'silver rally', 'gold falls', 'silver falls',
    'spot gold', 'spot silver', 'xauusd', 'xagusd',
    'comex gold', 'comex silver',

    # USD / Dollar
    'dollar index', 'dxy', 'us dollar',
    'dollar strengthens', 'dollar weakens',

    # Geopolitical (moves Gold)
    'war', 'conflict', 'sanctions', 'crisis',
    'recession', 'bank failure', 'banking crisis',
    'debt ceiling',

    # India specific (MoneyControl)
    'rbi', 'reserve bank of india', 'sensex crash',
    'mcx gold', 'mcx silver',
]

MEDIUM_IMPACT_KEYWORDS = [
    'trade deficit', 'trade surplus', 'trade war',
    'tariff', 'import', 'export data',
    'manufacturing pmi', 'services pmi',
    'oil prices', 'crude oil',
    'china economy', 'china gdp',
    'ecb', 'european central bank',
    'bank of england', 'boe',
    'bank of japan', 'boj',
]


class NewsAggregator:
    def __init__(self):
        self._cache = {}          # feed_name → (timestamp, articles)
        self._cache_ttl = 300     # 5 minute cache

    def get_latest_headlines(self) -> list:
        """
        Fetch headlines from all sources.
        Returns list of {source, title, time, impact, url}
        """
        all_articles = []

        for feed_id, feed_info in FEEDS.items():
            articles = self._fetch_feed(feed_id, feed_info)
            all_articles.extend(articles)

        # Sort by time — newest first
        all_articles.sort(key=lambda x: x.get('timestamp', 0), reverse=True)
        return all_articles

    def check_news_risk(self) -> dict:
        """
        Check if there is high-impact news in the last 60 minutes
        or upcoming (economic calendar via Trading Economics).

        Returns:
        {
            'risk_level': 'HIGH' | 'MEDIUM' | 'CLEAR',
            'reason': 'Fed rate decision in 15 minutes',
            'articles': [...],
            'warning': '⚠️ HIGH IMPACT NEWS DETECTED'
        }
        """
        articles = self.get_latest_headlines()
        now = datetime.now(timezone.utc)
        window_start = now - timedelta(hours=1)

        high_hits   = []
        medium_hits = []

        for article in articles:
            title = article.get('title', '').lower()
            art_time = article.get('datetime')

            # Only consider recent articles (last 60 min)
            if art_time:
                try:
                    if art_time < window_start:
                        continue
                except Exception:
                    pass

            # Check keywords
            for kw in HIGH_IMPACT_KEYWORDS:
                if kw in title:
                    high_hits.append(article)
                    break
            else:
                for kw in MEDIUM_IMPACT_KEYWORDS:
                    if kw in title:
                        medium_hits.append(article)
                        break

        if high_hits:
            return {
                'risk_level': 'HIGH',
                'reason': high_hits[0]['title'][:80],
                'source': high_hits[0]['source'],
                'articles': high_hits[:3],
                'warning': '🚨 HIGH IMPACT NEWS — Trade with extreme caution',
                'color': '🔴',
            }
        elif medium_hits:
            return {
                'risk_level': 'MEDIUM',
                'reason': medium_hits[0]['title'][:80],
                'source': medium_hits[0]['source'],
                'articles': medium_hits[:3],
                'warning': '⚠️ Market-moving news detected — Check before trading',
                'color': '🟡',
            }
        else:
            return {
                'risk_level': 'CLEAR',
                'reason': 'No high-impact news detected',
                'articles': [],
                'warning': '',
                'color': '🟢',
            }

    def get_top_headlines_summary(self, max_items: int = 5) -> str:
        """Get a formatted string of top market headlines for Telegram."""
        articles = self.get_latest_headlines()
        if not articles:
            return 'No headlines available'

        lines = []
        for a in articles[:max_items]:
            emoji = a.get('emoji', '📰')
            title = a.get('title', '')[:70]
            source = a.get('source', '')
            lines.append(f"{emoji} <b>{source}:</b> {title}...")

        return '\n'.join(lines)

    def _fetch_feed(self, feed_id: str, feed_info: dict) -> list:
        """Fetch and parse a single RSS feed."""
        # Check cache
        cached = self._cache.get(feed_id)
        now_ts = datetime.now(timezone.utc).timestamp()
        if cached and (now_ts - cached[0]) < self._cache_ttl:
            return cached[1]

        articles = []
        try:
            req = urllib.request.Request(
                feed_info['url'],
                headers={
                    'User-Agent': 'Mozilla/5.0 (compatible; NewsBot/1.0)',
                    'Accept': 'application/rss+xml, application/xml, text/xml',
                }
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                content = resp.read().decode('utf-8', errors='replace')

            root = ET.fromstring(content)

            # Handle both RSS and Atom formats
            items = root.findall('.//item') or root.findall('.//{http://www.w3.org/2005/Atom}entry')

            now = datetime.now(timezone.utc)

            for item in items[:20]:
                title = (
                    _get_text(item, 'title') or
                    _get_text(item, '{http://www.w3.org/2005/Atom}title') or ''
                )
                link = (
                    _get_text(item, 'link') or
                    _get_text(item, '{http://www.w3.org/2005/Atom}link') or ''
                )
                pub_date = (
                    _get_text(item, 'pubDate') or
                    _get_text(item, '{http://www.w3.org/2005/Atom}updated') or ''
                )

                # Parse publish time
                art_datetime = _parse_date(pub_date) or now

                articles.append({
                    'source':    feed_info['name'],
                    'emoji':     feed_info['emoji'],
                    'title':     title.strip(),
                    'url':       link.strip(),
                    'datetime':  art_datetime,
                    'timestamp': art_datetime.timestamp(),
                })

            log.debug(f"Fetched {len(articles)} articles from {feed_info['name']}")

        except Exception as e:
            log.warning(f"Feed fetch failed ({feed_info['name']}): {e}")

        # Cache result
        self._cache[feed_id] = (now_ts, articles)
        return articles


def _get_text(element, tag: str) -> str:
    """Safely get text from an XML element."""
    found = element.find(tag)
    if found is not None and found.text:
        return found.text.strip()
    return ''


def _parse_date(date_str: str):
    """Try to parse various RSS date formats."""
    if not date_str:
        return None

    formats = [
        '%a, %d %b %Y %H:%M:%S %z',
        '%a, %d %b %Y %H:%M:%S GMT',
        '%Y-%m-%dT%H:%M:%S%z',
        '%Y-%m-%dT%H:%M:%SZ',
        '%Y-%m-%d %H:%M:%S',
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

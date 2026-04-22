"""ACLED Connector - Armed Conflict Location & Event Data. Free API key from acleddata.com"""
import urllib.request, urllib.parse, json, logging
from datetime import datetime, timezone, timedelta

log = logging.getLogger("ALERT.ACLED")
ACLED_BASE = "https://api.acleddata.com/acled/read"

HIGH_IMPACT_COUNTRIES = ["Iran","Iraq","Syria","Israel","Palestine","Lebanon","Yemen",
    "Ukraine","Russia","Sudan","Libya","Saudi Arabia","United Arab Emirates"]
CHOKEPOINTS = ["Strait of Hormuz","Suez","Red Sea","Persian Gulf","Black Sea","Bab el-Mandeb"]

class ACLEDConnector:
    def __init__(self, api_key, email):
        self.api_key = api_key
        self.email = email
        self._cache = None
        self._cache_time = 0

    def get_recent_events(self, days=1):
        now = datetime.now(timezone.utc)
        if self._cache and (now.timestamp() - self._cache_time) < 3600:
            return self._cache
        since = (now - timedelta(days=days)).strftime("%Y-%m-%d")
        params = {"key": self.api_key, "email": self.email,
                  "event_date": since, "event_date_where": "BETWEEN",
                  "event_date2": now.strftime("%Y-%m-%d"), "limit": 100,
                  "fields": "event_date|event_type|actor1|country|location|fatalities|notes"}
        try:
            url = ACLED_BASE + "?" + urllib.parse.urlencode(params)
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.loads(r.read().decode())
            events = data.get("data", [])
            self._cache = events
            self._cache_time = now.timestamp()
            log.info(f"ACLED: {len(events)} events")
            return events
        except Exception as e:
            log.error(f"ACLED error: {e}")
            return []

    def assess_gold_impact(self, days=1):
        events = self.get_recent_events(days)
        if not events:
            return {"level": "CLEAR", "color": "green", "source": "ACLED",
                    "description": "No events", "gold_bias": "NEUTRAL", "reason": "Normal"}
        critical, high = [], []
        for ev in events:
            country = ev.get("country", "")
            etype = ev.get("event_type", "")
            notes = ev.get("notes", "")
            fat = int(ev.get("fatalities", 0) or 0)
            score = 0
            if etype in ["Explosions/Remote violence","Battles","Violence against civilians"]: score += 3
            elif etype == "Strategic developments": score += 2
            if any(c.lower() in country.lower() for c in HIGH_IMPACT_COUNTRIES): score += 2
            if any(c.lower() in (notes + ev.get("location","")).lower() for c in CHOKEPOINTS): score += 3
            if fat > 10: score += 2
            elif fat > 0: score += 1
            ev["_score"] = score
            if score >= 7: critical.append(ev)
            elif score >= 4: high.append(ev)
        if critical:
            top = sorted(critical, key=lambda x: x["_score"], reverse=True)[0]
            return {"level": "CRITICAL", "color": "red", "source": "ACLED",
                    "description": f"{top['country']}: {top['event_type']} ({top['fatalities']} fatalities)",
                    "gold_bias": "BUY", "reason": "Active conflict escalation"}
        elif high:
            top = sorted(high, key=lambda x: x["_score"], reverse=True)[0]
            return {"level": "HIGH", "color": "orange", "source": "ACLED",
                    "description": f"{top['country']}: {top['event_type']}",
                    "gold_bias": "NEUTRAL", "reason": "Elevated conflict activity"}
        return {"level": "CLEAR", "color": "green", "source": "ACLED",
                "description": "No high-impact events", "gold_bias": "NEUTRAL", "reason": "Normal"}

"""USGS Connector - Earthquakes near Gold-relevant regions. No API key needed."""
import urllib.request, json, logging
from datetime import datetime, timezone, timedelta

log = logging.getLogger("ALERT.USGS")
USGS_BASE = "https://earthquake.usgs.gov/fdsnws/event/1/query"

REGIONS = [
    {"name": "Iran/Persian Gulf",        "lat": 28,  "lon": 55,  "radius": 800},
    {"name": "Turkey/Syria",             "lat": 37,  "lon": 37,  "radius": 500},
    {"name": "Japan",                    "lat": 36,  "lon": 138, "radius": 600},
    {"name": "Indonesia/Malacca Strait", "lat": 0,   "lon": 110, "radius": 800},
    {"name": "Chile/Gold Mining",        "lat": -25, "lon": -70, "radius": 600},
]

class USGSConnector:
    def get_significant_events(self, hours=24, min_magnitude=5.5):
        try:
            now   = datetime.now(timezone.utc)
            start = (now - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%S")
            url   = f"{USGS_BASE}?format=geojson&starttime={start}&minmagnitude={min_magnitude}&orderby=magnitude"
            req   = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.loads(r.read().decode())
            features = data.get("features", [])
            if not features:
                return self._clear()
            gold_events = []
            for f in features:
                props = f.get("properties", {})
                geo   = f.get("geometry", {}).get("coordinates", [0, 0, 0])
                mag   = props.get("mag", 0)
                place = props.get("place", "")
                eq_lon, eq_lat = geo[0], geo[1]
                for region in REGIONS:
                    dist = ((eq_lat - region["lat"])**2 + (eq_lon - region["lon"])**2)**0.5 * 111
                    if dist <= region["radius"]:
                        gold_events.append({"magnitude": mag, "place": place,
                                            "region": region["name"], "dist_km": round(dist)})
                        break
            if not gold_events:
                return self._clear()
            gold_events.sort(key=lambda x: x["magnitude"], reverse=True)
            top = gold_events[0]
            if top["magnitude"] >= 7.0:
                level = "HIGH"; gold_bias = "BUY"
                reason = f"M{top['magnitude']} near {top['region']} — infrastructure risk"
            elif top["magnitude"] >= 6.0:
                level = "MEDIUM"; gold_bias = "NEUTRAL"
                reason = f"M{top['magnitude']} near {top['region']}"
            else:
                level = "LOW"; gold_bias = "NEUTRAL"
                reason = f"Minor seismic activity near {top['region']}"
            return {"level": level, "source": "USGS", "top_event": top,
                    "event_count": len(gold_events), "gold_bias": gold_bias,
                    "reason": reason, "description": f"M{top['magnitude']} near {top['region']}"}
        except Exception as e:
            log.warning(f"USGS error: {e}")
            return self._clear()

    def _clear(self):
        return {"level": "CLEAR", "source": "USGS", "gold_bias": "NEUTRAL",
                "reason": "No significant seismic activity",
                "description": "No earthquakes near key regions"}

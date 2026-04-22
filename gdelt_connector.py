"""GDELT Connector - Global news tone analysis. No API key needed."""
import urllib.request, urllib.parse, json, logging

log = logging.getLogger("ALERT.GDELT")
GDELT_DOC = "https://api.gdeltproject.org/api/v2/doc/doc"

class GDELTConnector:
    def get_conflict_intensity(self, hours=6):
        try:
            params = {"query": "conflict war sanctions military attack gold",
                      "mode": "ArtList", "maxrecords": "25",
                      "timespan": f"{hours}H", "format": "json", "sort": "ToneDesc"}
            url = GDELT_DOC + "?" + urllib.parse.urlencode(params)
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as r:
                data = json.loads(r.read().decode())
            articles = data.get("articles", [])
            if not articles:
                return self._neutral()
            tones = [float(a.get("tone", "0") or 0) for a in articles[:15]]
            avg_tone = sum(tones) / len(tones)
            min_tone = min(tones)
            neg_pct  = sum(1 for t in tones if t < -2) / len(tones) * 100
            if avg_tone < -5 or min_tone < -15:
                level = "CRITICAL"; gold_bias = "BUY"
                reason = f"Extreme negative news tone ({avg_tone:.1f})"
            elif avg_tone < -3 or neg_pct > 60:
                level = "HIGH"; gold_bias = "BUY"
                reason = f"Negative tone ({avg_tone:.1f}) — Gold safe haven demand likely"
            elif avg_tone < -1:
                level = "MEDIUM"; gold_bias = "NEUTRAL"
                reason = f"Slightly negative tone ({avg_tone:.1f})"
            else:
                level = "CLEAR"; gold_bias = "NEUTRAL"
                reason = f"Neutral tone ({avg_tone:.1f}) — calm conditions"
            log.info(f"GDELT: {level} tone={avg_tone:.1f}")
            return {"level": level, "source": "GDELT", "avg_tone": round(avg_tone, 2),
                    "min_tone": round(min_tone, 2), "neg_pct": round(neg_pct, 1),
                    "article_count": len(articles), "gold_bias": gold_bias, "reason": reason}
        except Exception as e:
            log.warning(f"GDELT error: {e}")
            return self._neutral()

    def _neutral(self):
        return {"level": "CLEAR", "source": "GDELT", "avg_tone": 0,
                "gold_bias": "NEUTRAL", "reason": "GDELT unavailable"}

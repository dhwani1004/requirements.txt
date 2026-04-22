"""BIS/FRED Connector - Central bank rates. No API key needed."""
import urllib.request, json, logging

log = logging.getLogger("ALERT.BIS")

class BISConnector:
    def get_policy_context(self):
        try:
            fed = self._get_fed_rate()
            ecb = self._get_ecb_rate()
            fed_rate = fed.get("rate", 5.25)
            fed_dir  = fed.get("direction", "stable")
            ecb_rate = ecb.get("rate", 4.0)
            if fed_rate > 5.0 and fed_dir in ("rising", "stable"):
                gold_impact = "BEARISH"
                reason = f"Fed {fed_rate}% — high rates suppress Gold"
            elif fed_dir == "falling" or fed_rate < 3.0:
                gold_impact = "BULLISH"
                reason = f"Fed {fed_rate}% falling — supports Gold"
            else:
                gold_impact = "NEUTRAL"
                reason = f"Fed {fed_rate}% — neutral for Gold"
            return {"source": "BIS/FRED", "fed_rate": fed_rate, "fed_direction": fed_dir,
                    "ecb_rate": ecb_rate, "gold_impact": gold_impact, "reason": reason,
                    "description": f"Fed:{fed_rate}% ({fed_dir}) ECB:{ecb_rate}%",
                    "level": "CLEAR", "gold_bias": "NEUTRAL"}
        except Exception as e:
            log.warning(f"BIS error: {e}")
            return {"source": "BIS", "gold_impact": "NEUTRAL", "fed_rate": 0, "ecb_rate": 0,
                    "description": "Rate data unavailable", "level": "CLEAR", "gold_bias": "NEUTRAL"}

    def _get_fed_rate(self):
        try:
            url = "https://api.stlouisfed.org/fred/series/observations?series_id=FEDFUNDS&file_type=json&limit=3&sort_order=desc"
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=8) as r:
                data = json.loads(r.read().decode())
            obs = data.get("observations", [])
            if len(obs) >= 2:
                cur  = float(obs[0]["value"])
                prev = float(obs[1]["value"])
                direction = "rising" if cur > prev else "falling" if cur < prev else "stable"
                return {"rate": cur, "direction": direction}
        except Exception as e:
            log.debug(f"FRED error: {e}")
        return {"rate": 5.25, "direction": "stable"}

    def _get_ecb_rate(self):
        try:
            url = "https://data-api.ecb.europa.eu/service/data/FM/B.U2.EUR.RT0.DFR.R.1.A7.MM.N?format=jsondata&lastNObservations=1"
            req = urllib.request.Request(url, headers={"Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=8) as r:
                data = json.loads(r.read().decode())
            obs = data["dataSets"][0]["series"]["0:0:0:0:0:0:0:0:0:0"]["observations"]
            return {"rate": float(list(obs.values())[-1][0])}
        except Exception as e:
            log.debug(f"ECB error: {e}")
        return {"rate": 4.0}

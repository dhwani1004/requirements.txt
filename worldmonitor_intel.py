"""
WorldMonitor Intelligence
Combines ACLED + GDELT + BIS + USGS into one Gold bias.
Runs every 15 min in background. Fires Telegram alert on escalation.
"""
import logging, threading, time
from datetime import datetime, timezone
from gdelt_connector import GDELTConnector
from bis_connector import BISConnector
from usgs_connector import USGSConnector

log = logging.getLogger("ALERT.WORLDMON")
LEVEL_SCORE = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1, "CLEAR": 0}

class WorldMonitorIntelligence:
    def __init__(self, telegram_alerter, acled_key="", acled_email=""):
        self.telegram = telegram_alerter
        self.gdelt    = GDELTConnector()
        self.bis      = BISConnector()
        self.usgs     = USGSConnector()
        self.acled    = None
        if acled_key and acled_email and acled_key != "YOUR_ACLED_KEY_HERE":
            try:
                from acled_connector import ACLEDConnector
                self.acled = ACLEDConnector(acled_key, acled_email)
                log.info("ACLED connector active")
            except Exception as e:
                log.warning(f"ACLED init failed: {e}")
        self._last       = {}
        self._last_level = "CLEAR"
        self._running    = False

    def start(self):
        self._running = True
        threading.Thread(target=self._loop, daemon=True).start()
        log.info("WorldMonitor intelligence started (15min cycle)")

    def stop(self):
        self._running = False

    def get_gold_bias(self):
        return self._last if self._last else self._assess()

    def _loop(self):
        while self._running:
            try:
                result = self._assess()
                self._last = result
                new_level  = result.get("overall_level", "CLEAR")
                prev_score = LEVEL_SCORE.get(self._last_level, 0)
                new_score  = LEVEL_SCORE.get(new_level, 0)
                if new_score >= 3 and new_score > prev_score:
                    self._send_alert(result)
                self._last_level = new_level
            except Exception as e:
                log.error(f"WorldMon loop: {e}")
            time.sleep(900)

    def _assess(self):
        sources = {}
        try: sources["gdelt"] = self.gdelt.get_conflict_intensity(hours=6)
        except Exception as e: log.warning(f"GDELT assess error: {e}")
        try: sources["bis"]   = self.bis.get_policy_context()
        except Exception as e: log.warning(f"BIS assess error: {e}")
        try: sources["usgs"]  = self.usgs.get_significant_events(hours=24)
        except Exception as e: log.warning(f"USGS assess error: {e}")
        if self.acled:
            try: sources["acled"] = self.acled.assess_gold_impact(days=1)
            except Exception as e: log.warning(f"ACLED assess error: {e}")

        scores   = [LEVEL_SCORE.get(r.get("level", "CLEAR"), 0) for r in sources.values()]
        mx       = max(scores) if scores else 0
        overall  = "CRITICAL" if mx >= 4 else "HIGH" if mx >= 3 else "MEDIUM" if mx >= 2 else "CLEAR"
        buy_ct   = sum(1 for r in sources.values() if r.get("gold_bias") == "BUY")
        bear_ct  = sum(1 for r in sources.values() if r.get("gold_impact") == "BEARISH")
        gdir     = "BULLISH" if buy_ct >= 2 else "BEARISH" if bear_ct >= 2 else "NEUTRAL"

        log.info(f"WorldMon: {overall} | Gold {gdir} | {list(sources.keys())}")
        return {"overall_level": overall, "gold_direction": gdir,
                "sources": sources, "buy_signals": buy_ct,
                "timestamp": datetime.now(timezone.utc).isoformat()}

    def _send_alert(self, result):
        level = result["overall_level"]
        gdir  = result["gold_direction"]
        em    = "\U0001f534" if level == "CRITICAL" else "\U0001f7e0"
        arrow = "\U00002b06 BUY" if gdir == "BULLISH" else "\U00002b07 SELL" if gdir == "BEARISH" else "\U00002194 Neutral"
        now   = datetime.now(timezone.utc).strftime("%H:%M UTC")
        sep   = "\u2501" * 20
        s     = result["sources"]
        msg   = f"{em} <b>WORLDMONITOR - {level}</b>\n{sep}\n\U0001f55b {now}\n<b>Gold Bias:</b> {arrow}\n{sep}\n"
        if "acled" in s: msg += f"\u2694 ACLED: {s['acled'].get('description','-')}\n"
        msg += f"\U0001f4f0 GDELT: {s.get('gdelt',{}).get('reason','-')}\n"
        msg += f"\U0001f3e6 BIS: {s.get('bis',{}).get('description','-')}\n"
        msg += f"\U0001f30d USGS: {s.get('usgs',{}).get('description','-')}\n"
        msg += f"{sep}\n<i>Context only — wait for bot signal before trading.</i>"
        self.telegram.send(msg)
        log.warning(f"WorldMon alert sent: {level} | Gold {gdir}")


def format_worldmon_line(assessment):
    if not assessment: return ""
    level = assessment.get("overall_level", "CLEAR")
    gdir  = assessment.get("gold_direction", "NEUTRAL")
    bis   = assessment.get("sources", {}).get("bis", {})
    gdelt = assessment.get("sources", {}).get("gdelt", {})
    arrow = "\U00002b06" if gdir == "BULLISH" else "\U00002b07" if gdir == "BEARISH" else "\U00002194"
    fed   = bis.get("fed_rate", 0)
    tone  = gdelt.get("avg_tone", 0)
    return (f"\U0001f30e <b>WorldMon:</b> {level} | Gold {arrow} {gdir}\n"
            f"  Fed:{fed}% | News tone:{float(tone):.1f}")
